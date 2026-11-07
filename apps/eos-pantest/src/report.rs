//! Verdicts, saving (CSV + WAV) and the GitHub issue report.

use crate::audio::DeviceInfo;
use crate::test::{Config, Row, TestKind, STUCK_DB};

pub const REPO: &str = "rfidmusic/EOS-4.71-beta";
const HARD_DB: f64 = 60.0; // one side more than 60 dB down = hard panned
const CENTRE_OK_DB: f64 = 0.1; // |L - R| at centre within this = balanced (4.70 / 4.71-beta: about -0.24 dB)
const SILENT_DB: f64 = -70.0; // a note whose attack and steady levels are all below this recorded no sound (noise floor about -96 dB)

/// Per test: where the sweep first reaches hard left / hard right, and what that means.
pub fn verdicts(rows: &[Row]) -> Vec<String> {
    let mut out = vec![];
    for kind in [TestKind::VoicePan, TestKind::MultiPan, TestKind::Cc10] {
        let rs: Vec<&Row> = rows.iter().filter(|r| r.test == kind).collect();
        if rs.is_empty() {
            continue;
        }
        let pair = rs[0].pair;
        let main: Vec<&&Row> = rs.iter().filter(|r| r.pair == pair).collect();
        let centre = if kind == TestKind::Cc10 { 64 } else { 0 };
        let hard_l = main.iter().filter(|r| r.l_db - r.r_db > HARD_DB).map(|r| r.value).max();
        let hard_r = main.iter().filter(|r| r.r_db - r.l_db > HARD_DB).map(|r| r.value).min();
        let (lo, hi) = if kind == TestKind::Cc10 { (0, 127) } else { (-64, 63) };
        let text = match (hard_l, hard_r) {
            (Some(l), Some(r)) => {
                let reach = (centre - l).max(r - centre);
                if (centre - l) <= 32 && (r - centre) <= 32 {
                    format!("{}: hard left already at {l}, hard right at {r} -> pan reaches the ends at half range (EOS 4.70 pan bug present)", kind.label())
                } else if l <= lo + 1 && r >= hi - 1 {
                    format!("{}: hard left only at {l}, hard right only at {r} -> full pan range (fixed, as in EOS 4.71-beta)", kind.label())
                } else {
                    format!("{}: hard left at {l}, hard right at {r} (reach {reach} steps from centre)", kind.label())
                }
            }
            _ => format!("{}: did not reach hard left/right in the measured values (check the outputs and levels)", kind.label()),
        };
        out.push(text);
        if let Some(c) = main.iter().find(|r| r.value == centre) {
            let d = c.l_db - c.r_db;
            out.push(if d.abs() <= CENTRE_OK_DB {
                format!("{}: centre ({centre}) balanced, L-R {d:+.2} dB (as in EOS 4.71-beta2)", kind.label())
            } else {
                format!(
                    "{}: centre ({centre}) L-R {d:+.2} dB ({} louder; EOS 4.70 and 4.71-beta are about 0.24 dB right-heavy)",
                    kind.label(),
                    if d < 0.0 { "right" } else { "left" }
                )
            });
        }
    }
    out.extend(stuck_verdicts(rows));
    out
}

/// RFX stuck pan: per phase, how many notes played at Pan 0 started (attack) or stayed (steady) off-centre.
fn stuck_verdicts(rows: &[Row]) -> Vec<String> {
    let rs: Vec<&Row> = rows.iter().filter(|r| r.test == TestKind::RfxStuck).collect();
    let Some(first) = rs.first() else { return vec![] };
    let pair = first.pair;
    let mut olds: Vec<i32> = rs.iter().map(|r| r.value).collect();
    olds.dedup();
    olds.into_iter()
        .map(|old| {
            let ph: Vec<&&Row> = rs.iter().filter(|r| r.value == old && r.pair == pair).collect();
            let from = if old == 100 { "a stereo preset".to_string() } else { format!("Pan {old}") };
            // Silence has L-R near 0 dB, so without this check it would read as "centred" (issue #12).
            let silent = ph.iter().filter(|r| [r.l_db, r.r_db, r.a_l_db, r.a_r_db].iter().all(|x| !(*x > SILENT_DB))).count();
            if silent == ph.len() {
                return format!("{}: after {from}, NO SOUND recorded on any of the {} notes (all below {SILENT_DB} dB): result not valid. Check that the test preset sounds on the E4 and that the selected audio inputs carry its outputs", TestKind::RfxStuck.label(), ph.len());
            }
            let stuck = ph.iter().filter(|r| (r.l_db - r.r_db).abs() > STUCK_DB).count();
            let click = ph.iter().filter(|r| (r.l_db - r.r_db).abs() <= STUCK_DB && (r.a_l_db - r.a_r_db).abs() > STUCK_DB).count();
            let worst = ph.iter().map(|r| r.a_l_db - r.a_r_db).fold(0.0f64, |m, x| if x.abs() > m.abs() { x } else { m });
            let mut v = if stuck + click == 0 {
                format!("{}: after {from}, all {} notes at Pan 0 centred from the attack on (no stuck pan)", TestKind::RfxStuck.label(), ph.len())
            } else {
                format!("{}: after {from}, {click} of {} notes started off-centre (attack) and {stuck} stayed off-centre", TestKind::RfxStuck.label(), ph.len())
            };
            v += &format!("; largest attack L-R {worst:+.1} dB");
            if silent > 0 {
                v += &format!("; {silent} notes recorded no sound and count as centred");
            }
            v
        })
        .collect()
}

pub fn csv(rows: &[Row]) -> String {
    let mut s = String::from("test,value,input_l,input_r,l_db,r_db,l_minus_r_db,step,attack_l_db,attack_r_db\n");
    for r in rows {
        s += &format!(
            "{},{},{},{},{:.2},{:.2},{:.2},{},{:.2},{:.2}\n",
            r.test.short(),
            r.value,
            r.pair.0 + 1,
            r.pair.1 + 1,
            r.l_db,
            r.r_db,
            r.l_db - r.r_db,
            r.step,
            r.a_l_db,
            r.a_r_db
        );
    }
    s
}

pub fn save(dir: &std::path::Path, rows: &[Row], takes: &[(String, Vec<f32>, usize, u32)], fw: &str, notes: &str,
            probe: &[String]) -> Result<usize, String> {
    let mut n = 0;
    std::fs::write(dir.join("pan_test.csv"), csv(rows)).map_err(|e| e.to_string())?;
    n += 1;
    std::fs::write(dir.join("pan_test_summary.txt"), format!("firmware: {fw}\n{}\n\nRFX probe:\n{}\n\nnotes:\n{notes}\n", verdicts(rows).join("\n"), probe.join("\n")))
        .map_err(|e| e.to_string())?;
    n += 1;
    for (name, data, ch, rate) in takes {
        let spec = hound::WavSpec { channels: *ch as u16, sample_rate: *rate, bits_per_sample: 32, sample_format: hound::SampleFormat::Float };
        let mut w = hound::WavWriter::create(dir.join(format!("{name}.wav")), spec).map_err(|e| e.to_string())?;
        for &s in data {
            w.write_sample(s).map_err(|e| e.to_string())?;
        }
        w.finalize().map_err(|e| e.to_string())?;
        n += 1;
    }
    Ok(n)
}

fn enc(s: &str) -> String {
    let mut o = String::with_capacity(s.len() * 3);
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => o.push(b as char),
            _ => o += &format!("%{b:02X}"),
        }
    }
    o
}

/// Longest issue URL we open. GitHub rejects longer ones with 400 "request URL is too long" (issue #11: 10,101),
/// and its sign-in redirect for a logged-out browser fails (500) above about 6,900 (measured 2026-11-06).
const MAX_URL: usize = 6000;

/// URL of a pre-filled "Pan test report" issue in the project repository. Header and verdicts always go in; then
/// the RFX probe lines, the measurement rows and the notes, each only while the encoded URL stays within MAX_URL.
/// Whatever is left out is in the saved pan_test.csv / pan_test_summary.txt.
pub fn issue_url(rows: &[Row], fw: &str, notes: &str, cfg: &Config, dev: Option<&DeviceInfo>, probe: &[String]) -> String {
    let title = format!("Pan test report: {fw}");
    let base = format!("https://github.com/{REPO}/issues/new?template=pan-test-report.md&labels=pan-test-report&title={}&body=", enc(&title));
    let fits = |body: &str| base.len() + enc(body).len() <= MAX_URL;
    let mut body = String::new();
    body += &format!("### Pan test report\n\n**Firmware:** {fw}\n**App:** eos-pantest {}\n**OS:** {}\n",
        env!("CARGO_PKG_VERSION"), std::env::consts::OS);
    body += &format!("**Program/key/velocity:** {}/{}/{}  **E4 device ID:** {}  **MIDI channel:** {}{}\n",
        cfg.program, cfg.key, cfg.velocity, cfg.device_id, cfg.channel,
        if cfg.extra_channels.trim().is_empty() { String::new() } else { format!(" (+{})", cfg.extra_channels.trim()) });
    if cfg.load_sound {
        body += "**Test sound:** loaded over MIDI (sample 999 -> preset 004, submix Main); every test played preset 004\n";
    }
    if let Some(d) = dev {
        body += &format!("**Audio input:** {}\n", d.label());
    }
    body += "\n#### Verdict\n";
    for v in verdicts(rows) {
        body += &format!("- {v}\n");
    }
    // Reserve room for the notes (up to 600 characters) and the "left out" lines.
    let notes = notes.trim();
    let notes: String = if notes.is_empty() { "(none)".into() } else { notes.chars().take(600).collect() };
    let notes_s = format!("\n#### Notes\n{notes}\n");
    const CUT: &str = "\nThe full results are in the saved folder (**Save CSV + WAV**): please zip it and attach it here.\n";
    let room = |body: &str, extra: &str| fits(&format!("{body}{extra}\n(… 999 more probe lines in pan_test_summary.txt)\n{notes_s}{CUT}"));
    let mut cut = false;
    if !probe.is_empty() {
        body += "\n#### RFX probe\n";
        for (i, p) in probe.iter().enumerate() {
            let line = format!("- {p}\n");
            if !room(&body, &line) {
                body += &format!("(… {} more probe lines in pan_test_summary.txt)\n", probe.len() - i);
                cut = true;
                break;
            }
            body += &line;
        }
    }
    let head = "\n#### Measurements (L/R RMS 300-1000 ms after the onset; RFX stuck pan: value = old pan, note, attack = first 5 ms)\n\n| test | value | inputs | L dB | R dB | L-R dB | note | attack L-R dB |\n|---|---|---|---|---|---|---|---|\n";
    if room(&body, head) {
        body += head;
        for (i, r) in rows.iter().enumerate() {
            let att = if r.test == TestKind::RfxStuck { format!("{} | {:+.2}", r.step, r.a_l_db - r.a_r_db) } else { " | ".into() };
            let line = format!("| {} | {} | {}/{} | {:.2} | {:.2} | {:+.2} | {att} |\n", r.test.short(), r.value, r.pair.0 + 1, r.pair.1 + 1, r.l_db, r.r_db, r.l_db - r.r_db);
            if !room(&body, &line) {
                body += &format!("\n(… {} more rows in pan_test.csv)\n", rows.len() - i);
                cut = true;
                break;
            }
            body += &line;
        }
    } else if !rows.is_empty() {
        body += &format!("\n(… {} measurement rows in pan_test.csv)\n", rows.len());
        cut = true;
    }
    body += &notes_s;
    if cut {
        body += CUT;
    }
    format!("{base}{}", enc(&body))
}

pub fn open_browser(url: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let r = std::process::Command::new("open").arg(url).spawn();
    #[cfg(target_os = "windows")]
    let r = std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", url]).spawn();
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let r = std::process::Command::new("xdg-open").arg(url).spawn();
    r.map(|_| ()).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(old: i32, step: u32, steady: (f64, f64), attack: (f64, f64)) -> Row {
        Row { test: TestKind::RfxStuck, value: old, pair: (0, 1), l_db: steady.0, r_db: steady.1, step, a_l_db: attack.0, a_r_db: attack.1 }
    }

    #[test]
    fn stuck_pan_counts_clicks_and_stuck_notes() {
        let rows = vec![
            row(-64, 1, (-20.0, -20.0), (-20.0, -20.2)), // clean
            row(-64, 2, (-20.0, -20.1), (-18.0, -40.0)), // starts on the old (left) side
            row(-64, 3, (-15.0, -30.0), (-15.0, -30.0)), // stays left
            row(63, 1, (-20.0, -20.0), (-20.0, -20.0)),
        ];
        let v = stuck_verdicts(&rows);
        assert_eq!(v.len(), 2);
        assert!(v[0].contains("after Pan -64, 1 of 3 notes started off-centre (attack) and 1 stayed off-centre"), "{}", v[0]);
        assert!(v[0].contains("+22.0 dB"), "{}", v[0]);
        assert!(v[1].contains("after Pan 63, all 1 notes at Pan 0 centred"), "{}", v[1]);
    }

    #[test]
    fn stuck_silence_is_not_centred() {
        // issue #12: every take at the noise floor; must not say "no stuck pan"
        let rows: Vec<Row> = (1..=16).map(|i| row(-64, i, (-96.5, -96.4), (-96.7, -97.1))).collect();
        let v = stuck_verdicts(&rows);
        assert!(v[0].contains("NO SOUND") && !v[0].contains("no stuck pan"), "{}", v[0]);
        // one silent note among sounding ones is counted, not fatal
        let mut rows: Vec<Row> = (1..=3).map(|i| row(63, i, (-20.0, -20.0), (-20.0, -20.0))).collect();
        rows.push(row(63, 4, (-96.5, -96.4), (-96.7, -97.1)));
        let v = stuck_verdicts(&rows);
        assert!(v[0].contains("no stuck pan") && v[0].contains("1 notes recorded no sound"), "{}", v[0]);
    }

    #[test]
    fn issue_url_fits_github_limit() {
        // 48 RFX rows + 41 pan rows and 7 long probe lines, as in issue #11 (10,101-character URL in 0.4.0).
        let mut rows: Vec<Row> = (0..48).map(|i| row(-64 + (i / 16) * 64, (i % 16 + 1) as u32, (-98.15, -98.08), (-25.4, -28.4))).collect();
        rows.extend((0..41).map(|i| Row { test: TestKind::VoicePan, value: i - 20, pair: (0, 1), l_db: -28.25, r_db: -97.89,
                                         step: 0, a_l_db: f64::NAN, a_r_db: f64::NAN }));
        let probe: Vec<String> = (0..7).map(|_| "RFX probe after the fill with voice Pan -64, Pan now 0: E-mu orphan counters 0 / 0 / 0, live orphan partners 0; 128 channels: mono 0 / stereo 0 / partner 0 / unused 128; last RFX pan 0: 39, last RFX pan = -64: 81, not yet written: 0".to_string()).collect();
        let notes = "Emu E4 Platinum inc. RFX-32 — FX engine disabled ✓ ".repeat(40);
        let url = issue_url(&rows, "EOS 4.71-beta2 build 4", &notes, &Config::default(), None, &probe);
        assert!(url.len() <= MAX_URL, "{}", url.len());
        assert!(url.contains(&enc("more rows in pan_test.csv")), "rows not cut");
        assert!(url.contains(&enc("#### Verdict")) && url.contains(&enc("#### Notes")));
        // a short report goes in whole
        let url = issue_url(&rows[..3], "b4", "", &Config::default(), None, &probe[..1]);
        assert!(!url.contains(&enc("more rows")) && !url.contains(&enc("please zip it")));
    }

    #[test]
    fn csv_has_attack_columns() {
        let c = csv(&[row(-64, 2, (-20.0, -20.0), (-18.0, -40.0))]);
        assert!(c.starts_with("test,value,input_l,input_r,l_db,r_db,l_minus_r_db,step,attack_l_db,attack_r_db\n"));
        assert!(c.contains("rfx_stuck,-64,1,2,-20.00,-20.00,0.00,2,-18.00,-40.00"));
    }
}
