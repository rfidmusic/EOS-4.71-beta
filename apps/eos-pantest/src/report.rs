//! Verdicts, saving (CSV + WAV) and the GitHub issue report.

use crate::audio::DeviceInfo;
use crate::test::{Config, Row, TestKind, STUCK_DB};

pub const REPO: &str = "rfidmusic/EOS-4.71-beta";
const HARD_DB: f64 = 60.0; // one side more than 60 dB down = hard panned
const CENTRE_OK_DB: f64 = 0.1; // |L - R| at centre within this = balanced (4.70 / 4.71-beta: about -0.24 dB)

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
            let stuck = ph.iter().filter(|r| (r.l_db - r.r_db).abs() > STUCK_DB).count();
            let click = ph.iter().filter(|r| (r.l_db - r.r_db).abs() <= STUCK_DB && (r.a_l_db - r.a_r_db).abs() > STUCK_DB).count();
            let worst = ph.iter().map(|r| r.a_l_db - r.a_r_db).fold(0.0f64, |m, x| if x.abs() > m.abs() { x } else { m });
            let from = if old == 100 { "a stereo preset".to_string() } else { format!("Pan {old}") };
            let mut v = if stuck + click == 0 {
                format!("{}: after {from}, all {} notes at Pan 0 centred from the attack on (no stuck pan)", TestKind::RfxStuck.label(), ph.len())
            } else {
                format!("{}: after {from}, {click} of {} notes started off-centre (attack) and {stuck} stayed off-centre", TestKind::RfxStuck.label(), ph.len())
            };
            v += &format!("; largest attack L-R {worst:+.1} dB");
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

/// URL of a pre-filled "Pan test report" issue in the project repository.
pub fn issue_url(rows: &[Row], fw: &str, notes: &str, cfg: &Config, dev: Option<&DeviceInfo>, probe: &[String]) -> String {
    let mut body = String::new();
    body += &format!("### Pan test report\n\n**Firmware:** {fw}\n**App:** eos-pantest {}\n**OS:** {}\n",
        env!("CARGO_PKG_VERSION"), std::env::consts::OS);
    body += &format!("**Program/key/velocity:** {}/{}/{}  **E4 device ID:** {}  **MIDI channel:** {}{}\n",
        cfg.program, cfg.key, cfg.velocity, cfg.device_id, cfg.channel,
        if cfg.extra_channels.trim().is_empty() { String::new() } else { format!(" (+{})", cfg.extra_channels.trim()) });
    if let Some(d) = dev {
        body += &format!("**Audio input:** {}\n", d.label());
    }
    body += "\n#### Verdict\n";
    for v in verdicts(rows) {
        body += &format!("- {v}\n");
    }
    if !probe.is_empty() {
        body += "\n#### RFX probe\n";
        for p in probe {
            body += &format!("- {p}\n");
        }
    }
    body += "\n#### Measurements (L/R RMS 300-1000 ms after the onset; RFX stuck pan: value = old pan, note, attack = first 5 ms)\n\n| test | value | inputs | L dB | R dB | L-R dB | note | attack L-R dB |\n|---|---|---|---|---|---|---|---|\n";
    for r in rows {
        let att = if r.test == TestKind::RfxStuck { format!("{} | {:+.2}", r.step, r.a_l_db - r.a_r_db) } else { " | ".into() };
        body += &format!("| {} | {} | {}/{} | {:.2} | {:.2} | {:+.2} | {att} |\n", r.test.short(), r.value, r.pair.0 + 1, r.pair.1 + 1, r.l_db, r.r_db, r.l_db - r.r_db);
    }
    body += &format!("\n#### Notes\n{}\n", if notes.trim().is_empty() { "(none)" } else { notes.trim() });
    // keep the URL within what browsers and GitHub accept
    if body.len() > 6000 {
        body.truncate(6000);
        body += "\n… (table truncated: attach pan_test.csv)\n";
    }
    let title = format!("Pan test report: {fw}");
    format!("https://github.com/{REPO}/issues/new?template=pan-test-report.md&labels=pan-test-report&title={}&body={}", enc(&title), enc(&body))
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
    fn csv_has_attack_columns() {
        let c = csv(&[row(-64, 2, (-20.0, -20.0), (-18.0, -40.0))]);
        assert!(c.starts_with("test,value,input_l,input_r,l_db,r_db,l_minus_r_db,step,attack_l_db,attack_r_db\n"));
        assert!(c.contains("rfx_stuck,-64,1,2,-20.00,-20.00,0.00,2,-18.00,-40.00"));
    }
}
