//! EOS Pan Test: measures how far the E4's pan controls really pan (EOS 4.70 bug: voice Pan, Multimode
//! Pan and MIDI CC10 reach hard left/right at half range; fixed in EOS 4.71-beta; the centre is about
//! 0.24 dB right-heavy in 4.70 and 4.71-beta, balanced in 4.71-beta2), and probes the RFX-32 "stuck pan"
//! reports (a new note starting at the pan an earlier note on that channel had; notes/rfx_bugs.md).
//!
//! Sends the same editor SysEx and notes as the project's hardware tests (tools/hw_pan_test.py), records
//! the chosen audio input pair(s) and reports L/R levels per setting. Results can be saved (CSV + WAV) and
//! reported to the project's GitHub repository as a pre-filled issue (opened in the browser; nothing is
//! sent without the user submitting it).
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod audio;
mod report;
mod test;

use eframe::egui;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Receiver;
use std::sync::Arc;
use std::time::Duration;
use test::{Config, Event, Row, TestKind};

struct App {
    outs: Vec<String>,
    ins: Vec<String>,
    out_sel: usize,
    in_sel: usize,
    devices: Vec<audio::DeviceInfo>,
    dev_sel: usize,
    pairs: Vec<(usize, usize, bool)>,
    cfg: Config,
    firmware: String,
    notes: String,
    rows: Vec<Row>,
    log: Vec<String>,
    progress: f32,
    running: Option<(Arc<AtomicBool>, Receiver<Event>)>,
    last_dir: Option<std::path::PathBuf>,
    takes: Vec<(String, Vec<f32>, usize, u32)>,
    probe: Vec<String>,
}

impl App {
    fn new() -> Self {
        let mut a = App {
            outs: vec![],
            ins: vec![],
            out_sel: 0,
            in_sel: 0,
            devices: vec![],
            dev_sel: 0,
            pairs: vec![],
            cfg: Config::default(),
            firmware: "EOS 4.70".into(),
            notes: String::new(),
            rows: vec![],
            log: vec!["Connect the E4 MIDI in/out and its outputs to an audio input, choose them below, then Run.".into()],
            progress: 0.0,
            running: None,
            last_dir: None,
            takes: vec![],
            probe: vec![],
        };
        a.refresh();
        a
    }

    fn refresh(&mut self) {
        self.outs = eos_core::midi::output_names();
        self.ins = eos_core::midi::input_names();
        self.out_sel = self.out_sel.min(self.outs.len().saturating_sub(1));
        self.match_input();
        self.devices = audio::input_devices();
        self.dev_sel = self.dev_sel.min(self.devices.len().saturating_sub(1));
        self.reset_pairs();
    }

    fn match_input(&mut self) {
        if let Some(o) = self.outs.get(self.out_sel) {
            if let Some(i) = self.ins.iter().position(|n| n == o) {
                self.in_sel = i;
            }
        }
        self.in_sel = self.in_sel.min(self.ins.len().saturating_sub(1));
    }

    fn reset_pairs(&mut self) {
        let ch = self.devices.get(self.dev_sel).map(|d| d.channels).unwrap_or(2) as usize;
        self.pairs = (0..ch / 2).map(|k| (2 * k, 2 * k + 1, k == 0)).collect();
    }

    fn start(&mut self) {
        let (Some(o), Some(i), Some(d)) =
            (self.outs.get(self.out_sel), self.ins.get(self.in_sel), self.devices.get(self.dev_sel))
        else {
            self.log.push("Choose MIDI output, MIDI input and audio device.".into());
            return;
        };
        let pairs: Vec<(usize, usize)> = self.pairs.iter().filter(|p| p.2).map(|p| (p.0, p.1)).collect();
        if pairs.is_empty() {
            self.log.push("Select at least one input pair.".into());
            return;
        }
        let mut cfg = self.cfg.clone();
        cfg.midi_out = o.clone();
        cfg.midi_in = i.clone();
        cfg.audio_device = d.name.clone();
        cfg.pairs = pairs;
        self.rows.clear();
        self.takes.clear();
        self.probe.clear();
        let stop = Arc::new(AtomicBool::new(false));
        let rx = test::spawn(cfg, stop.clone());
        self.running = Some((stop, rx));
        self.progress = 0.0;
    }

    fn summary(&self) -> String {
        report::verdicts(&self.rows).join("\n")
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        if let Some((_, rx)) = &self.running {
            let mut done = false;
            while let Ok(ev) = rx.try_recv() {
                match ev {
                    Event::Log(s) => self.log.push(s),
                    Event::Row(r) => self.rows.push(r),
                    Event::Probe(s) => {
                        self.log.push(s.clone());
                        self.probe.push(s)
                    }
                    Event::Take(name, data, ch, rate) => self.takes.push((name, data, ch, rate)),
                    Event::Progress(p) => self.progress = p,
                    Event::Done(r) => {
                        if let Err(e) = r {
                            self.log.push(format!("Stopped: {e}"));
                        } else {
                            self.log.push("Finished.".into());
                            for v in report::verdicts(&self.rows) {
                                self.log.push(v);
                            }
                        }
                        done = true;
                    }
                }
            }
            if done {
                self.running = None;
            }
            ctx.request_repaint_after(Duration::from_millis(100));
        }
        let busy = self.running.is_some();

        egui::SidePanel::left("setup").min_width(360.0).show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
                ui.heading("Setup");
                ui.add_enabled_ui(!busy, |ui| {
                    ui.strong("MIDI");
                    let prev = self.out_sel;
                    egui::ComboBox::from_label("output to E4")
                        .width(220.0)
                        .selected_text(self.outs.get(self.out_sel).cloned().unwrap_or("(none)".into()))
                        .show_ui(ui, |ui| {
                            for (i, n) in self.outs.iter().enumerate() {
                                ui.selectable_value(&mut self.out_sel, i, n);
                            }
                        });
                    if prev != self.out_sel {
                        self.match_input();
                    }
                    egui::ComboBox::from_label("input from E4")
                        .width(220.0)
                        .selected_text(self.ins.get(self.in_sel).cloned().unwrap_or("(none)".into()))
                        .show_ui(ui, |ui| {
                            for (i, n) in self.ins.iter().enumerate() {
                                ui.selectable_value(&mut self.in_sel, i, n);
                            }
                        });
                    ui.horizontal(|ui| {
                        ui.label("E4 device ID");
                        ui.add(egui::DragValue::new(&mut self.cfg.device_id).range(0..=127));
                        ui.label("MIDI channel");
                        ui.add(egui::DragValue::new(&mut self.cfg.channel).range(1..=16));
                    });
                    ui.horizontal(|ui| {
                        ui.label("Program");
                        ui.add(egui::DragValue::new(&mut self.cfg.program).range(0..=127));
                        ui.label("Key");
                        ui.add(egui::DragValue::new(&mut self.cfg.key).range(0..=127));
                        ui.label("Velocity");
                        ui.add(egui::DragValue::new(&mut self.cfg.velocity).range(1..=127));
                    });
                    ui.horizontal(|ui| {
                        ui.label("Also play on channels");
                        ui.text_edit_singleline(&mut self.cfg.extra_channels)
                            .on_hover_text("e.g. 2,3,4 for Multimode copies routed to sub outputs");
                    });
                    ui.checkbox(&mut self.cfg.prepare, "Prepare preset (select it, cords to 0, filter open)")
                        .on_hover_text("Edits the preset's edit buffer only; nothing is saved.");
                    ui.separator();
                    ui.strong("Audio input");
                    let prevd = self.dev_sel;
                    egui::ComboBox::from_label("device")
                        .width(240.0)
                        .selected_text(self.devices.get(self.dev_sel).map(|d| d.label()).unwrap_or("(none)".into()))
                        .show_ui(ui, |ui| {
                            for (i, d) in self.devices.iter().enumerate() {
                                ui.selectable_value(&mut self.dev_sel, i, d.label());
                            }
                        });
                    if prevd != self.dev_sel {
                        self.reset_pairs();
                    }
                    ui.label("Input pairs to measure (L/R):");
                    egui::Grid::new("pairs").show(ui, |ui| {
                        for (k, p) in self.pairs.iter_mut().enumerate() {
                            ui.checkbox(&mut p.2, format!("{}/{}", p.0 + 1, p.1 + 1));
                            if k % 4 == 3 {
                                ui.end_row();
                            }
                        }
                    });
                    if ui.button("Refresh MIDI and audio").clicked() {
                        self.refresh();
                    }
                    ui.separator();
                    ui.strong("Tests");
                    ui.checkbox(&mut self.cfg.tests[0], TestKind::VoicePan.label());
                    ui.checkbox(&mut self.cfg.tests[1], TestKind::MultiPan.label());
                    ui.checkbox(&mut self.cfg.tests[2], TestKind::Cc10.label());
                    ui.checkbox(&mut self.cfg.tests[3], TestKind::RfxStuck.label())
                        .on_hover_text("For units with an RFX-32: fills every channel hard left, then hard right, \
                                        then plays notes at Pan 0 and checks they start and stay centred.");
                    if self.cfg.tests[3] {
                        ui.horizontal(|ui| {
                            ui.label("Voices");
                            ui.selectable_value(&mut self.cfg.voices, 64, "64");
                            ui.selectable_value(&mut self.cfg.voices, 128, "128");
                            ui.label("Notes per phase");
                            ui.add(egui::DragValue::new(&mut self.cfg.stuck_notes).range(4..=64));
                        });
                        ui.horizontal(|ui| {
                            ui.label("Stereo preset (-1 = skip)");
                            ui.add(egui::DragValue::new(&mut self.cfg.stereo_program).range(-1..=127))
                                .on_hover_text("A preset with a stereo sample: adds a mono-after-stereo phase.");
                        });
                        ui.checkbox(&mut self.cfg.probe, "Read the RFX probe (EOS 4.71-beta2 build 4)");
                    }
                    ui.horizontal(|ui| {
                        ui.label("Pan values");
                        ui.text_edit_singleline(&mut self.cfg.pan_values);
                    });
                    ui.horizontal(|ui| {
                        ui.label("CC10 values");
                        ui.text_edit_singleline(&mut self.cfg.cc_values);
                    });
                    ui.separator();
                    ui.strong("Report");
                    ui.horizontal(|ui| {
                        ui.label("Firmware");
                        egui::ComboBox::from_id_salt("fw")
                            .selected_text(&self.firmware)
                            .show_ui(ui, |ui| {
                                for f in ["EOS 4.70", "EOS 4.71-beta", "EOS 4.71-beta2", "EOS 4.71-beta2 build 3", "EOS 4.71-beta2 build 4",
                                          "other (see notes)"] {
                                    ui.selectable_value(&mut self.firmware, f.to_string(), f);
                                }
                            });
                    });
                    ui.label("Notes (E4 model, RFX card, outputs used, ...):");
                    ui.text_edit_multiline(&mut self.notes);
                });
            });
        });

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.horizontal(|ui| {
                if !busy {
                    if ui.button("▶ Run tests").clicked() {
                        self.start();
                    }
                } else if ui.button("■ Stop").clicked() {
                    if let Some((stop, _)) = &self.running {
                        stop.store(true, Ordering::Relaxed);
                    }
                }
                ui.add(egui::ProgressBar::new(self.progress).show_percentage().desired_width(220.0));
                if ui.add_enabled(!busy && !self.rows.is_empty(), egui::Button::new("Save CSV + WAV…")).clicked() {
                    if let Some(dir) = rfd::FileDialog::new().pick_folder() {
                        match report::save(&dir, &self.rows, &self.takes, &self.firmware, &self.notes, &self.probe) {
                            Ok(n) => self.log.push(format!("Saved {n} files to {}", dir.display())),
                            Err(e) => self.log.push(format!("Save failed: {e}")),
                        }
                        self.last_dir = Some(dir);
                    }
                }
                if ui
                    .add_enabled(!busy && !self.rows.is_empty(), egui::Button::new("Report to GitHub…"))
                    .on_hover_text("Opens a pre-filled issue in the project repository in your browser; you review and submit it.")
                    .clicked()
                {
                    let url = report::issue_url(&self.rows, &self.firmware, &self.notes, &self.cfg, self.devices.get(self.dev_sel), &self.probe);
                    match report::open_browser(&url) {
                        Ok(_) => self.log.push("Opened the GitHub issue form in your browser. Attach the saved CSV/WAV if you like.".into()),
                        Err(e) => self.log.push(format!("Could not open the browser: {e}")),
                    }
                }
            });
            if !self.rows.is_empty() {
                ui.label(egui::RichText::new(self.summary()).strong());
            }
            ui.separator();
            egui::ScrollArea::vertical().id_salt("rows").max_height(330.0).show(ui, |ui| {
                egui::Grid::new("res").striped(true).show(ui, |ui| {
                    for h in ["test", "value", "inputs", "L dB", "R dB", "L−R dB", "note", "attack L−R dB"] {
                        ui.strong(h);
                    }
                    ui.end_row();
                    for r in &self.rows {
                        ui.label(r.test.label());
                        ui.label(r.value.to_string());
                        ui.label(format!("{}/{}", r.pair.0 + 1, r.pair.1 + 1));
                        ui.label(format!("{:.2}", r.l_db));
                        ui.label(format!("{:.2}", r.r_db));
                        ui.label(format!("{:+.2}", r.l_db - r.r_db));
                        if r.test == TestKind::RfxStuck {
                            ui.label(r.step.to_string());
                            ui.label(format!("{:+.2}", r.a_l_db - r.a_r_db));
                        }
                        ui.end_row();
                    }
                });
            });
            ui.separator();
            egui::ScrollArea::vertical().id_salt("log").stick_to_bottom(true).show(ui, |ui| {
                for l in &self.log {
                    ui.label(l);
                }
            });
        });
    }
}

/// Command-line mode (same test code, no window):
/// eos-pantest --cli --midi-out NAME [--midi-in NAME] --audio NAME [--pair L,R]... [--tests voice,multi,cc10,rfx]
///             [--device-id N] [--channel N] [--program N] [--key N] [--extra-channels 2,3,4]
///             [--voices 64|128] [--stuck-notes N] [--stereo-program N] [--no-probe]
fn cli(args: &[String]) -> Result<(), String> {
    let mut cfg = Config::default();
    let mut i = 0;
    let mut tests: Option<String> = None;
    while i < args.len() {
        let v = args.get(i + 1).cloned().unwrap_or_default();
        match args[i].as_str() {
            "--midi-out" => cfg.midi_out = v,
            "--midi-in" => cfg.midi_in = v,
            "--audio" => cfg.audio_device = v,
            "--pair" => {
                let p: Vec<usize> = v.split(',').filter_map(|x| x.trim().parse().ok()).collect();
                if p.len() == 2 && p[0] >= 1 && p[1] >= 1 {
                    cfg.pairs.push((p[0] - 1, p[1] - 1));
                }
            }
            "--tests" => tests = Some(v),
            "--device-id" => cfg.device_id = v.parse().map_err(|_| "device id")?,
            "--channel" => cfg.channel = v.parse().map_err(|_| "channel")?,
            "--program" => cfg.program = v.parse().map_err(|_| "program")?,
            "--key" => cfg.key = v.parse().map_err(|_| "key")?,
            "--extra-channels" => cfg.extra_channels = v,
            "--pan-values" => cfg.pan_values = v,
            "--cc-values" => cfg.cc_values = v,
            "--voices" => cfg.voices = v.parse().map_err(|_| "voices")?,
            "--stuck-notes" => cfg.stuck_notes = v.parse().map_err(|_| "stuck notes")?,
            "--stereo-program" => cfg.stereo_program = v.parse().map_err(|_| "stereo program")?,
            "--no-probe" => {
                cfg.probe = false;
                i += 1;
                continue;
            }
            _ => {
                i += 1;
                continue;
            }
        }
        i += 2;
    }
    if cfg.midi_in.is_empty() {
        cfg.midi_in = cfg.midi_out.clone();
    }
    if cfg.pairs.is_empty() {
        cfg.pairs.push((0, 1));
    }
    if let Some(t) = tests {
        cfg.tests = [t.contains("voice"), t.contains("multi"), t.contains("cc10"), t.contains("rfx")];
    }
    let rows = test::run_blocking(&cfg)?;
    for v in report::verdicts(&rows) {
        println!("{v}");
    }
    Ok(())
}

fn main() -> eframe::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--cli") {
        if let Err(e) = cli(&args[1..]) {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
        return Ok(());
    }
    if args.iter().any(|a| a == "--list") {
        println!("MIDI out: {:?}\nMIDI in: {:?}", eos_core::midi::output_names(), eos_core::midi::input_names());
        for d in audio::input_devices() {
            println!("audio in: {}", d.label());
        }
        return Ok(());
    }
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([1100.0, 760.0]).with_title("EOS Pan Test"),
        ..Default::default()
    };
    eframe::run_native("EOS Pan Test", opts, Box::new(|_| Ok(Box::new(App::new()))))
}
