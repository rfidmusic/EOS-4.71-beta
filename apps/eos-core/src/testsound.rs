//! The test sound, sent to a running EOS over MIDI alone (no disk, no front panel; notes/sysex_load_research.md,
//! checked on an E4 Platinum 2026-11-06):
//!   1. the sample: a 441 Hz sine, 4,410 frames at 44.1 kHz, looped over whole periods, as an MMA MIDI Sample
//!      Dump (SDS). EOS takes an SDS header on any page (parser 0x136B64 -> 0x175014); sample numbers 1..999.
//!   2. the preset: an editor preset dump (`F0 18 21 dd 55 0D ...`), which creates the preset from EOS's default
//!      "Untitled Preset" and applies the values through the normal parameter setters: one voice, one zone, the
//!      sample on keys 0..127, original key 72 (441 Hz at key 72), every other value the parameter table default
//!      (voice sustains, filter open, no cords, submix Main).
//! Both live in RAM only and are lost at power-off.

/// Sample frames, rate and loop (start, end; end exclusive, whole 100-frame periods).
pub const RATE: u32 = 44_100;
pub const FRAMES: usize = 4_410;
pub const LOOP: (usize, usize) = (200, 4_400);

/// The sine (441 Hz = exactly 100 frames per period).
pub fn sine() -> Vec<i16> {
    (0..FRAMES).map(|i| (16_000.0 * (2.0 * std::f64::consts::PI * i as f64 / 100.0).sin()) as i16).collect()
}

fn b7(v: u32, n: usize) -> impl Iterator<Item = u8> {
    (0..n).map(move |i| ((v >> (7 * i)) & 0x7f) as u8)
}

/// MMA SDS: header and data packets (120 bytes = 40 words each, 16-bit words left-justified in 3 bytes, offset
/// binary; checksum = XOR of 7E cc 02 kk and the data). `dev` is the SDS channel (the E4's device ID).
pub fn sds(dev: u8, num: u16, words: &[i16], rate: u32, lp: Option<(usize, usize)>) -> (Vec<u8>, Vec<Vec<u8>>) {
    let period = (1e9 / rate as f64).round() as u32;
    let (ls, le, lt) = match lp {
        Some((s, e)) => (s as u32, e as u32, 0x00),
        None => (0, 0, 0x7f),
    };
    let mut hdr = vec![0xf0, 0x7e, dev & 0x7f, 0x01];
    hdr.extend(b7(num as u32, 2));
    hdr.push(16);
    hdr.extend(b7(period, 3));
    hdr.extend(b7(words.len() as u32, 3));
    hdr.extend(b7(ls, 3));
    hdr.extend(b7(le, 3));
    hdr.extend([lt, 0xf7]);
    let mut data = Vec::with_capacity(words.len() * 3);
    for &w in words {
        let u = (w as i32 + 32768) as u32;
        data.extend([((u >> 9) & 0x7f) as u8, ((u >> 2) & 0x7f) as u8, ((u << 5) & 0x60) as u8]);
    }
    let pkts = data
        .chunks(120)
        .enumerate()
        .map(|(k, c)| {
            let mut body = vec![0x7e, dev & 0x7f, 0x02, (k & 0x7f) as u8];
            body.extend_from_slice(c);
            body.resize(124, 0);
            let cs = body.iter().fold(0u8, |a, &b| a ^ b) & 0x7f;
            let mut m = vec![0xf0];
            m.extend(body);
            m.extend([cs, 0xf7]);
            m
        })
        .collect();
    (hdr, pkts)
}

/// Defaults of editor parameter ids 0..182 (parameter table 0x63E58, clamped to each descriptor's range).
const DEFAULTS: [i16; 183] = [
    0, 0, -1, -1, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 127, 0, 0, 0, 127, 0, 0, 1, 0, 0,
    0, 0, 0, 0, 72, 0, 0, 127, 0, 0, 0, 127, 0, 0, 0, 127, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0, 100, 0, 100, 20, 0,
    0, 0, 0, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 0, 100, 0,
    100, 20, 0, 0, 0, 64, 0, 0, 0, 0, 64, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    100, 0, 100, 0, 100, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0,
];

fn w14(v: i32, out: &mut Vec<u8>) {
    let v = (v as u32) & 0x3fff;
    out.extend([(v & 0x7f) as u8, ((v >> 7) & 0x7f) as u8]);
}

/// Editor preset dump (handshake form, command 0x0D): header `55 0D 01 00 <len, 4 x 7 bits>`, then packets
/// `55 0D 02 <n> <256 data bytes> <cs>`, cs = !sum & 0x7F; only the last packet may be short. Data: preset number,
/// 16-byte name, ids 0..21, link count 0, voice count 1, ids 37..182, zone count 1 (one zone: the voice-level
/// sample and key values go to zone 0). The E4 answers each message with WAIT `55 7C`, then ACK `55 7F <n>`.
pub fn preset_dump(dev: u8, preset: u16, sample: u16, name: &str, orig_key: u8) -> Vec<Vec<u8>> {
    let mut v: Vec<i32> = DEFAULTS.iter().map(|&x| x as i32).collect();
    v[38] = sample as i32;
    v[44] = orig_key as i32;
    v[45] = 0; // low key
    v[47] = 127; // high key
    let mut data = Vec::new();
    w14(preset as i32, &mut data);
    let mut nm: Vec<u8> = name.bytes().filter(|b| (0x20..0x7f).contains(b)).take(16).collect();
    nm.resize(16, b' ');
    data.extend(nm);
    for &x in &v[..22] {
        w14(x, &mut data);
    }
    w14(0, &mut data); // links
    w14(1, &mut data); // voices
    for &x in &v[37..183] {
        w14(x, &mut data);
    }
    w14(1, &mut data); // zones
    let mut msgs = vec![[vec![0xf0, 0x18, 0x21, dev & 0x7f, 0x55, 0x0d, 0x01, 0x00], b7(data.len() as u32, 4).collect(), vec![0xf7]].concat()];
    for (n, p) in data.chunks(256).enumerate() {
        let cs = !p.iter().fold(0u8, |a, &b| a.wrapping_add(b)) & 0x7f;
        msgs.push([vec![0xf0, 0x18, 0x21, dev & 0x7f, 0x55, 0x0d, 0x02, ((n + 1) & 0x7f) as u8], p.to_vec(), vec![cs, 0xf7]].concat());
    }
    msgs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sds_header_matches_e4_test() {
        let (h, p) = sds(1, 100, &sine(), RATE, Some(LOOP));
        // sample 100, 16 bits, 22676 ns, 4410 words, loop 200..4400 forward
        assert_eq!(h, [0xF0, 0x7E, 0x01, 0x01, 0x64, 0x00, 0x10, 0x14, 0x31, 0x01, 0x3A, 0x22, 0x00, 0x48, 0x01, 0x00,
                       0x30, 0x22, 0x00, 0x00, 0xF7]);
        assert_eq!(p.len(), 111);
        assert!(p.iter().all(|m| m.len() == 127 && m.iter().skip(1).take(125).all(|&b| b < 0x80)));
    }

    #[test]
    fn preset_dump_layout() {
        let m = preset_dump(1, 4, 100, "RFX Pan Sine", 72);
        assert_eq!(m[0], [0xF0, 0x18, 0x21, 0x01, 0x55, 0x0D, 0x01, 0x00, 0x68, 0x02, 0x00, 0x00, 0xF7]); // 360 bytes
        assert_eq!((m.len(), m[1].len(), m[2].len()), (3, 266, 114));
        assert_eq!(&m[1][8..12], &[4, 0, b'R', b'F']);
        for p in &m[1..] {
            let d = &p[8..p.len() - 2];
            assert_eq!(p[p.len() - 2], !d.iter().fold(0u8, |a, &b| a.wrapping_add(b)) & 0x7f);
        }
    }
}

use crate::remote::Remote;
use std::time::{Duration, Instant};

/// Preset and sample slots the test sound goes into (RAM only; whatever was there is replaced).
pub const PRESET: u16 = 4;
pub const SAMPLE: u16 = 999;
pub const NAME: &str = "RFX Pan Sine";

fn wait(rm: &Remote, ms: u64, mut f: impl FnMut(&[u8]) -> Option<bool>) -> Option<bool> {
    let t0 = Instant::now();
    while t0.elapsed() < Duration::from_millis(ms) {
        if let Ok(m) = rm.rx.recv_timeout(Duration::from_millis(10)) {
            if let Some(r) = f(&m) {
                return Some(r);
            }
        }
    }
    None
}

/// Editor read-back `55 <cmd> n n` -> reply `55 <reply> ...` (sample name 0A -> 09, voice count 16 -> 17).
fn ask(rm: &mut Remote, cmd: u8, reply: u8, n: u16) -> Option<Vec<u8>> {
    while rm.rx.try_recv().is_ok() {}
    rm.short(&[0xf0, 0x18, 0x21, rm.dev & 0x7f, 0x55, cmd, (n & 0x7f) as u8, (n >> 7) as u8, 0xf7]).ok()?;
    let mut got = None;
    wait(rm, 1000, |m| {
        (m.len() > 8 && m[1] == 0x18 && m[2] == 0x21 && m[4] == 0x55 && m[5] == reply).then(|| {
            got = Some(m.to_vec());
            true
        })
    });
    got
}

/// Sends the sample (SDS, handshake if the E4 answers the header, else open loop) and the preset (preset dump,
/// waiting for each ACK), then reads both back. `log` gets progress lines.
pub fn load(rm: &mut Remote, mut log: impl FnMut(String)) -> Result<(), String> {
    let dev = rm.dev;
    let (hdr, pkts) = sds(dev, SAMPLE, &sine(), RATE, Some(LOOP));
    while rm.rx.try_recv().is_ok() {}
    rm.short(&hdr)?;
    // SDS replies: F0 7E cc <7F ACK | 7E NAK | 7C WAIT | 7D CANCEL> pp F7
    let sds_reply = |m: &[u8]| (m.len() >= 5 && m[1] == 0x7e && matches!(m[3], 0x7f | 0x7e | 0x7d)).then(|| m[3]);
    let mut r = None;
    wait(rm, 2000, |m| sds_reply(m).map(|x| { r = Some(x); true }));
    if r == Some(0x7d) {
        return Err("the E4 cancelled the sample dump (not enough sample memory?)".into());
    }
    let handshake = r == Some(0x7f);
    log(format!("Sending the test sample ({} packets, {})...", pkts.len(), if handshake { "handshake" } else { "open loop" }));
    for (k, p) in pkts.iter().enumerate() {
        for attempt in 0..3 {
            rm.short(p)?;
            if !handshake {
                std::thread::sleep(Duration::from_millis(60));
                break;
            }
            let mut r = None;
            wait(rm, 2000, |m| sds_reply(m).map(|x| { r = Some(x); true }));
            match r {
                Some(0x7f) | None => break, // no reply: carry on, as the standard allows
                Some(0x7d) => return Err(format!("the E4 cancelled the sample dump at packet {k}")),
                _ if attempt == 2 => return Err(format!("sample packet {k} refused 3 times")),
                _ => {}
            }
        }
    }
    std::thread::sleep(Duration::from_millis(300));
    match ask(rm, 0x0a, 0x09, SAMPLE) {
        // F0 18 21 dd 55 09 <sample lo hi> <16-byte name> F7
        Some(m) if m.len() >= 25 => {
            let name = String::from_utf8_lossy(&m[8..24]).trim().to_string();
            if name.starts_with("Empty") {
                return Err(format!("sample {SAMPLE} is still empty after the dump"));
            }
            log(format!("Sample {SAMPLE} received ('{name}')."));
        }
        _ => return Err("no answer to the sample name request (check MIDI in and the device ID)".into()),
    }
    for (k, m) in preset_dump(dev, PRESET, SAMPLE, NAME, 72).iter().enumerate() {
        while rm.rx.try_recv().is_ok() {}
        rm.short(m)?;
        // 55 7C = WAIT, 55 7F n = ACK, 55 7E = NAK, 55 7D = CANCEL
        let mut r = None;
        wait(rm, 3000, |x| {
            (x.len() >= 7 && x[1] == 0x18 && x[2] == 0x21 && x[4] == 0x55 && matches!(x[5], 0x7f | 0x7e | 0x7d)).then(|| {
                r = Some(x[5]);
                true
            })
        });
        match r {
            Some(0x7f) => {}
            Some(x) => return Err(format!("the E4 refused preset dump message {k} ({x:02X})")),
            None => return Err(format!("no answer to preset dump message {k}")),
        }
    }
    match ask(rm, 0x16, 0x17, PRESET) {
        // F0 18 21 dd 55 17 <count lo hi> F7
        Some(m) if m.len() >= 9 && (m[6] as u16 | (m[7] as u16) << 7) == 1 => {
            log(format!("Preset {PRESET:03} '{NAME}' created (sample {SAMPLE} on every key)."));
            Ok(())
        }
        Some(m) => Err(format!("preset {PRESET:03} has an unexpected voice count ({:02X?})", &m[6..m.len().min(9)])),
        None => Err("no answer to the voice count request".into()),
    }
}
