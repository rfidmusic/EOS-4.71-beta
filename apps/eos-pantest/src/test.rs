//! The pan test sequence (same as tools/hw_pan_test.py / hw_lfosync_test.Rig.setup):
//! program change, select the preset/voice for editing, cord amounts 0, filter wide open, then for each
//! value: set voice Pan (editor id 40) / Multimode Pan (id 249) / send CC10, play one note, record, and
//! measure L/R RMS 300..1000 ms after the onset on every selected input pair.
//!
//! RFX stuck pan (notes/rfx_bugs.md): fill every channel at a hard pan (voice Pan -64, then +63; optionally with
//! a stereo preset), set Pan 0, then play single notes and compare the attack (first 5 ms after the onset) with
//! the steady part. A note that starts on the old side, or stays there, is the bug users reported with an RFX-32.
//! With EOS 4.71-beta2 build 4 the app also reads the RFX probe (SysEx parameter 195): E-mu's orphan-partner
//! counters, live orphans, and each channel's voice type and last RFX pan.

use crate::audio::Recorder;
use eos_core::remote::{id, Remote};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum TestKind {
    VoicePan,
    MultiPan,
    Cc10,
    RfxStuck,
}

impl TestKind {
    pub fn label(&self) -> &'static str {
        match self {
            TestKind::VoicePan => "Voice Pan (editor id 40)",
            TestKind::MultiPan => "Multimode Pan (editor id 249)",
            TestKind::Cc10 => "MIDI CC10 pan",
            TestKind::RfxStuck => "RFX stuck pan (old pan on new notes)",
        }
    }
    pub fn short(&self) -> &'static str {
        match self {
            TestKind::VoicePan => "voice_pan",
            TestKind::MultiPan => "multi_pan",
            TestKind::Cc10 => "cc10",
            TestKind::RfxStuck => "rfx_stuck",
        }
    }
}

#[derive(Clone)]
pub struct Config {
    pub midi_out: String,
    pub midi_in: String,
    pub audio_device: String,
    pub pairs: Vec<(usize, usize)>,
    pub device_id: u8,
    pub channel: u8,
    pub extra_channels: String,
    pub program: u8,
    pub key: u8,
    pub velocity: u8,
    pub prepare: bool,
    pub tests: [bool; 4],
    pub pan_values: String,
    pub cc_values: String,
    /// RFX stuck pan: preset it plays (test bank 004: the sine on every key, so the fill notes use every
    /// channel), voices on the unit (64 or 128), notes per phase, stereo preset for the mono-after-stereo phase
    /// (-1 = skip, test bank 001), and whether the firmware has the RFX probe (build 4).
    pub stuck_program: u8,
    pub voices: u32,
    pub stuck_notes: u32,
    pub stereo_program: i32,
    pub probe: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            midi_out: String::new(),
            midi_in: String::new(),
            audio_device: String::new(),
            pairs: vec![],
            device_id: 1,
            channel: 1,
            extra_channels: String::new(),
            program: 0,
            key: 72,
            velocity: 100,
            prepare: true,
            tests: [true, true, true, false],
            pan_values: "-64,-48,-40,-32,-24,-16,-8,0,8,16,24,32,40,48,63".into(),
            cc_values: "0,16,32,48,63,64,65,80,96,112,127".into(),
            stuck_program: 4,
            voices: 128,
            stuck_notes: 16,
            stereo_program: -1,
            probe: true,
        }
    }
}

#[derive(Clone)]
pub struct Row {
    pub test: TestKind,
    /// the pan set (RFX stuck pan: the old pan the channels were filled with; 100 = stereo fill)
    pub value: i32,
    pub pair: (usize, usize),
    pub l_db: f64,
    pub r_db: f64,
    /// RFX stuck pan: note number within the phase, and L/R RMS over the first 5 ms after the onset (NaN otherwise)
    pub step: u32,
    pub a_l_db: f64,
    pub a_r_db: f64,
}

pub enum Event {
    Log(String),
    Row(Row),
    Probe(String),
    Take(String, Vec<f32>, usize, u32),
    Progress(f32),
    Done(Result<(), String>),
}

fn parse_list(s: &str) -> Vec<i32> {
    s.split(|c: char| c == ',' || c.is_whitespace()).filter_map(|t| t.trim().parse().ok()).collect()
}

fn db(x: f64) -> f64 {
    20.0 * (x.max(1e-12)).log10()
}

/// Onset (frame index): first 1 ms window whose RMS over the selected channels exceeds 20 % of the max.
fn onset(d: &[f32], ch: usize, sel: &[usize], rate: u32) -> usize {
    let w = (rate as usize / 1000).max(1);
    let frames = d.len() / ch;
    let env: Vec<f64> = (0..frames / w)
        .map(|k| {
            let mut s = 0.0;
            for f in k * w..(k + 1) * w {
                for &c in sel {
                    let v = d[f * ch + c] as f64;
                    s += v * v;
                }
            }
            (s / (w * sel.len()) as f64).sqrt()
        })
        .collect();
    let mx = env.iter().cloned().fold(0.0, f64::max);
    env.iter().position(|&e| e > 0.2 * mx).unwrap_or(0) * w
}

fn rms(d: &[f32], ch: usize, c: usize, a: usize, b: usize) -> f64 {
    let frames = d.len() / ch;
    let (a, b) = (a.min(frames), b.min(frames));
    if b <= a {
        return 0.0;
    }
    let s: f64 = (a..b).map(|f| (d[f * ch + c] as f64).powi(2)).sum();
    (s / (b - a) as f64).sqrt()
}

/// Runs the test on this thread (command-line mode), printing as it goes.
pub fn run_blocking(cfg: &Config) -> Result<Vec<Row>, String> {
    let (tx, rx) = channel();
    let stop = AtomicBool::new(false);
    let r = run(cfg, &stop, &tx);
    drop(tx);
    let mut rows = vec![];
    for ev in rx {
        match ev {
            Event::Log(s) | Event::Probe(s) => println!("{s}"),
            Event::Row(row) => {
                println!("{:10} {:5} {:>2}/{:<2} L {:7.2} R {:7.2} L-R {:+7.2}", row.test.short(), row.value,
                         row.pair.0 + 1, row.pair.1 + 1, row.l_db, row.r_db, row.l_db - row.r_db);
                if row.test == TestKind::RfxStuck {
                    println!("{:16} note {:2} attack L {:7.2} R {:7.2} L-R {:+7.2}", "", row.step, row.a_l_db, row.a_r_db,
                             row.a_l_db - row.a_r_db);
                }
                rows.push(row)
            }
            _ => {}
        }
    }
    r.map(|_| rows)
}

pub fn spawn(cfg: Config, stop: Arc<AtomicBool>) -> Receiver<Event> {
    let (tx, rx) = channel();
    std::thread::spawn(move || {
        let r = run(&cfg, &stop, &tx);
        let _ = tx.send(Event::Done(r));
    });
    rx
}

fn sleep(ms: u64) {
    std::thread::sleep(Duration::from_millis(ms));
}

fn run(cfg: &Config, stop: &AtomicBool, tx: &Sender<Event>) -> Result<(), String> {
    let mut out = eos_core::midi::open_output(&cfg.midi_out)?;
    let (_conn, mrx) = eos_core::midi::open_input(&cfg.midi_in)?;
    let rec = Recorder::open(&cfg.audio_device)?;
    let log = |s: String| {
        let _ = tx.send(Event::Log(s));
    };
    log(format!("Audio: {} channels at {} Hz.", rec.channels, rec.rate));
    for &(l, r) in &cfg.pairs {
        if l >= rec.channels || r >= rec.channels {
            return Err(format!("input pair {}/{} not available on this device", l + 1, r + 1));
        }
    }
    let ch0 = (cfg.channel - 1) & 15;
    let mut chans = vec![ch0];
    for c in parse_list(&cfg.extra_channels) {
        if (1..=16).contains(&c) && !chans.contains(&((c - 1) as u8)) {
            chans.push((c - 1) as u8);
        }
    }
    let mut rm = Remote { out: &mut out, rx: &mrx, dev: cfg.device_id };
    select_preset(&mut rm, &chans, cfg.program, cfg.prepare)?;
    match rm.get(id::VOICE_PAN) {
        Some(v) => log(format!("E4 answers on device ID {} (voice Pan reads {v}).", cfg.device_id)),
        None => log(format!(
            "No answer from the E4 on device ID {} (check the MIDI input and the E4's MIDI device ID). Continuing.",
            cfg.device_id
        )),
    }

    let pans = parse_list(&cfg.pan_values);
    let ccs = parse_list(&cfg.cc_values);
    let kinds = [TestKind::VoicePan, TestKind::MultiPan, TestKind::Cc10];
    let jobs: Vec<(TestKind, i32)> = kinds
        .iter()
        .zip(cfg.tests.iter())
        .filter(|(_, &on)| on)
        .flat_map(|(&k, _)| {
            let vals = if k == TestKind::Cc10 { ccs.clone() } else { pans.clone() };
            vals.into_iter().map(move |v| (k, v))
        })
        .collect();
    let rate = rec.rate as usize;
    let stuck_phases = if cfg.tests[3] { if cfg.stereo_program >= 0 { 3 } else { 2 } } else { 0 };
    let total = (jobs.len() + stuck_phases) as f32;
    let mut prev: Option<TestKind> = None;
    for (n, &(kind, v)) in jobs.iter().enumerate() {
        if stop.load(Ordering::Relaxed) {
            return Err("stopped".into());
        }
        // Pans add up: centre voice Pan, Multimode Pan and CC10 before each test so only one moves.
        if prev != Some(kind) {
            centre(&mut rm, &chans)?;
            sleep(150);
            prev = Some(kind);
        }
        match kind {
            TestKind::VoicePan => rm.set(id::VOICE_PAN, v)?,
            TestKind::MultiPan => rm.set(id::MULTI_PAN, v)?,
            TestKind::Cc10 => {
                for &c in &chans {
                    rm.short(&[0xB0 | c, 10, v.clamp(0, 127) as u8])?;
                }
            }
            TestKind::RfxStuck => unreachable!(),
        }
        sleep(250);
        rec.clear();
        let t0 = Instant::now();
        sleep(200);
        for &c in &chans {
            rm.short(&[0x90 | c, cfg.key, cfg.velocity])?;
        }
        sleep(1000);
        for &c in &chans {
            rm.short(&[0x80 | c, cfg.key, 0])?;
        }
        while t0.elapsed() < Duration::from_millis(1400) {
            sleep(10);
        }
        let d = rec.take();
        let chn = rec.channels;
        let sel: Vec<usize> = cfg.pairs.iter().flat_map(|p| [p.0, p.1]).collect();
        let on = onset(&d, chn, &sel, rec.rate);
        let (a, b) = (on + rate * 300 / 1000, on + rate * 1000 / 1000);
        for &(l, r) in &cfg.pairs {
            let row = Row { test: kind, value: v, pair: (l, r), l_db: db(rms(&d, chn, l, a, b)), r_db: db(rms(&d, chn, r, a, b)),
                            step: 0, a_l_db: f64::NAN, a_r_db: f64::NAN };
            let _ = tx.send(Event::Row(row));
        }
        let _ = tx.send(Event::Take(format!("{}_{v}", kind.short()), d, chn, rec.rate));
        let _ = tx.send(Event::Progress((n + 1) as f32 / total));
    }
    if cfg.tests[3] {
        if cfg.stuck_program != cfg.program {
            log(format!("RFX stuck pan uses preset {:03}.", cfg.stuck_program));
            select_preset(&mut rm, &chans, cfg.stuck_program, cfg.prepare)?;
        }
        centre(&mut rm, &chans)?;
        sleep(150);
        let mut phases: Vec<(i32, Option<u8>)> = vec![(-64, None), (63, None)];
        if cfg.stereo_program >= 0 {
            phases.push((100, Some(cfg.stereo_program.clamp(0, 127) as u8)));
        }
        probe_report(&mut rm, cfg, "before the RFX stuck-pan test", None, tx);
        for (k, &(old, stereo)) in phases.iter().enumerate() {
            if stop.load(Ordering::Relaxed) {
                return Err("stopped".into());
            }
            stuck_phase(&mut rm, cfg, &chans, &rec, old, stereo, stop, tx)?;
            let _ = tx.send(Event::Progress((jobs.len() + k + 1) as f32 / total));
        }
        if cfg.stuck_program != cfg.program {
            select_preset(&mut rm, &chans, cfg.program, false)?;
        }
    }
    // leave everything centred
    centre(&mut rm, &chans)?;
    Ok(())
}

/// Program change on every playing channel and make it the editor's current preset/voice; with `prepare`,
/// also cords to 0 and filter wide open (not saved).
fn select_preset(rm: &mut Remote, chans: &[u8], program: u8, prepare: bool) -> Result<(), String> {
    for &c in chans {
        rm.short(&[0xC0 | c, program & 0x7f])?;
    }
    sleep(500);
    rm.set(223, program as i32)?; // current preset (editor)
    rm.set(225, 0)?; // current voice
    sleep(100);
    if prepare {
        for n in 0..18 {
            rm.set(id::cord(n).2, 0)?;
        }
        rm.set(id::FILTER_TYPE, 0)?;
        sleep(150);
        rm.set(id::FILTER_FREQ, 255)?;
        rm.set(id::FILTER_Q, 0)?;
        sleep(300);
    }
    Ok(())
}

/// One RFX stuck-pan phase: fill the channels at `old` pan (or with the stereo preset), centre, play single notes.
#[allow(clippy::too_many_arguments)]
fn stuck_phase(rm: &mut Remote, cfg: &Config, chans: &[u8], rec: &Recorder, old: i32, stereo: Option<u8>,
               stop: &AtomicBool, tx: &Sender<Event>) -> Result<(), String> {
    let log = |s: String| {
        let _ = tx.send(Event::Log(s));
    };
    let c0 = chans[0];
    let what = match stereo {
        Some(p) => format!("stereo preset {p}"),
        None => format!("voice Pan {old}"),
    };
    // Fill: hold notes on spread keys until every channel has played (stereo notes take two channels).
    if let Some(p) = stereo {
        rm.short(&[0xC0 | c0, p])?;
        sleep(500);
    } else {
        rm.set(id::VOICE_PAN, old)?;
        sleep(200);
    }
    let per = if stereo.is_some() { cfg.voices / 2 } else { cfg.voices }.clamp(1, 128) as i32;
    let keys: Vec<u8> = (0..per).map(|i| (cfg.key as i32 - per / 2 + i).clamp(0, 127) as u8).collect();
    log(format!("RFX stuck pan: filling {} channels with {what} ({} held notes)...", cfg.voices, keys.len()));
    for &k in &keys {
        rm.short(&[0x90 | c0, k, cfg.velocity])?;
        sleep(15);
    }
    sleep(400);
    for &k in &keys {
        rm.short(&[0x80 | c0, k, 0])?;
    }
    sleep(1500);
    if stereo.is_some() {
        rm.short(&[0xC0 | c0, cfg.stuck_program & 0x7f])?;
        sleep(500);
    }
    rm.set(id::VOICE_PAN, 0)?;
    sleep(300);
    probe_report(rm, cfg, &format!("after the fill with {what}, Pan now 0"), Some(if stereo.is_some() { 0 } else { old }), tx);
    let value = if stereo.is_some() { 100 } else { old };
    let (mut clicks, mut stuck) = (0, 0);
    for step in 1..=cfg.stuck_notes {
        if stop.load(Ordering::Relaxed) {
            return Err("stopped".into());
        }
        rec.clear();
        let t0 = Instant::now();
        sleep(150);
        rm.short(&[0x90 | c0, cfg.key, cfg.velocity])?;
        sleep(1000);
        rm.short(&[0x80 | c0, cfg.key, 0])?;
        while t0.elapsed() < Duration::from_millis(1350) {
            sleep(10);
        }
        let d = rec.take();
        let chn = rec.channels;
        let rate = rec.rate as usize;
        let sel: Vec<usize> = cfg.pairs.iter().flat_map(|p| [p.0, p.1]).collect();
        let on = onset(&d, chn, &sel, rec.rate);
        let (a0, a1) = (on.saturating_sub(rate / 2000), on + rate * 5 / 1000);
        let (s0, s1) = (on + rate * 300 / 1000, on + rate);
        for (i, &(l, r)) in cfg.pairs.iter().enumerate() {
            let row = Row { test: TestKind::RfxStuck, value, pair: (l, r), l_db: db(rms(&d, chn, l, s0, s1)),
                            r_db: db(rms(&d, chn, r, s0, s1)), step, a_l_db: db(rms(&d, chn, l, a0, a1)),
                            a_r_db: db(rms(&d, chn, r, a0, a1)) };
            if i == 0 {
                let (att, st) = (row.a_l_db - row.a_r_db, row.l_db - row.r_db);
                if st.abs() > STUCK_DB {
                    stuck += 1;
                } else if att.abs() > STUCK_DB {
                    clicks += 1;
                }
            }
            let _ = tx.send(Event::Row(row));
        }
        let _ = tx.send(Event::Take(format!("rfx_stuck_{}_{step}", if stereo.is_some() { "stereo".into() } else { old.to_string() }),
                                    d, chn, rec.rate));
    }
    log(format!("RFX stuck pan after {what}: {clicks} of {} notes started off-centre, {stuck} stayed off-centre.",
                cfg.stuck_notes));
    probe_report(rm, cfg, &format!("after the test notes ({what})"), None, tx);
    Ok(())
}

/// |L-R| above this (dB) on a note played at Pan 0 = off-centre.
pub const STUCK_DB: f64 = 3.0;

/// Reads one RFX probe word (SysEx parameter 195, build 4): command, then three 11-bit pieces.
fn probe(rm: &mut Remote, cmd: i32) -> Option<u32> {
    rm.set(195, 0).ok()?;
    sleep(30);
    rm.set(195, cmd).ok()?;
    sleep(50);
    let mut v = 0u32;
    for k in 0..3 {
        let p = rm.get(195)?;
        if !(0..=0x7FF).contains(&p) {
            return None;
        }
        v |= (p as u32) << (11 * k);
    }
    Some(v)
}

/// Probe summary: E-mu's counters, live orphans, voice types, and how many channels' last RFX pan is `old`.
fn probe_report(rm: &mut Remote, cfg: &Config, when: &str, old: Option<i32>, tx: &Sender<Event>) {
    if !cfg.probe {
        return;
    }
    let send = |s: String| {
        let _ = tx.send(Event::Probe(s));
    };
    let (Some(a), Some(b)) = (probe(rm, 16), probe(rm, 17)) else {
        send(format!("RFX probe {when}: no answer (needs EOS 4.71-beta2 build 4)."));
        return;
    };
    let (mut types, mut pans) = ([0u32; 16], std::collections::BTreeMap::<i32, u32>::new());
    let mut read = 0;
    for n in 0..cfg.voices.min(128) as i32 {
        if let Some(w) = probe(rm, 64 + n) {
            read += 1;
            types[(w >> 28) as usize] += 1;
            let pan = (w & 0xFFFF) as u16 as i16 as i32;
            *pans.entry(pan).or_default() += 1;
        }
    }
    let ty = format!("mono {} / stereo {} / partner {} / unused {}", types[1], types[2] + types[4], types[8], types[0]);
    let invalid = pans.get(&-129).copied().unwrap_or(0);
    let at_old = old.map(|o| format!(", last RFX pan = {o}: {}", pans.get(&o).copied().unwrap_or(0))).unwrap_or_default();
    let at_c = pans.get(&0).copied().unwrap_or(0);
    send(format!(
        "RFX probe {when}: E-mu orphan counters {} / {} / {}, live orphan partners {}; {read} channels: {ty}; \
         last RFX pan 0: {at_c}{at_old}, not yet written: {invalid}",
        a >> 16, a & 0xFFFF, b >> 16, b & 0xFFFF
    ));
}

fn centre(rm: &mut Remote, chans: &[u8]) -> Result<(), String> {
    for &c in chans {
        rm.short(&[0xB0 | c, 10, 64])?;
    }
    rm.set(id::MULTI_PAN, 0)?;
    rm.set(id::VOICE_PAN, 0)?;
    Ok(())
}
