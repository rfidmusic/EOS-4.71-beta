//! EOS Flasher: builds EOS 4.71-beta2 build 3 (or build 2, 4.71-beta, or the original 4.70) from E-mu's EOS470.EXE and sends it to an
//! E-mu E4 Ultra over MIDI (MIDI File Dump with the loader's handshake). E-mu's firmware is not part
//! of this app: it patches the user's own copy and verifies input and output by SHA-256.
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

use eframe::egui;
use eos_core::patch::{self, Version};
use eos_core::{filedump, midi, sender};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Receiver};
use std::sync::Arc;
use std::time::Duration;

enum Msg {
    Log(String),
    Progress(f32),
    Finished(Result<(), String>),
}

struct App {
    source: Option<std::path::PathBuf>,
    data: Option<Vec<u8>>,
    source_status: String,
    version: Version,
    built: Option<(Vec<Vec<u8>>, String)>,
    outs: Vec<String>,
    ins: Vec<String>,
    out_sel: usize,
    in_sel: usize,
    log: Vec<String>,
    progress: f32,
    running: Option<(Arc<AtomicBool>, Receiver<Msg>)>,
}

impl App {
    fn new() -> Self {
        let mut a = App {
            source: None,
            data: None,
            source_status: "Choose E-mu's EOS470.EXE (or an EOS 4.70 floppy image).".into(),
            version: Version::Build3,
            built: None,
            outs: vec![],
            ins: vec![],
            out_sel: 0,
            in_sel: 0,
            log: vec![],
            progress: 0.0,
            running: None,
        };
        a.refresh_ports();
        for p in [patch::LFOCK, patch::BUILD3, patch::BETA2, patch::BETA1] {
            let (name, steps, bytes, copied) = patch::info(p);
            let moved = if copied > 0 { format!(", {copied} bytes moved within your 4.70") } else { String::new() };
            a.log.push(format!("Patch: {name} ({steps} steps, {bytes} bytes{moved}; applied to your own 4.70 image)."));
        }
        a
    }

    fn refresh_ports(&mut self) {
        self.outs = midi::output_names();
        self.ins = midi::input_names();
        self.out_sel = self.out_sel.min(self.outs.len().saturating_sub(1));
        self.match_input();
    }

    fn match_input(&mut self) {
        if let Some(o) = self.outs.get(self.out_sel) {
            if let Some(i) = self.ins.iter().position(|n| n == o) {
                self.in_sel = i;
            }
        }
        self.in_sel = self.in_sel.min(self.ins.len().saturating_sub(1));
    }

    fn load(&mut self, path: std::path::PathBuf) {
        self.built = None;
        match std::fs::read(&path) {
            Ok(d) => {
                match eos_core::build_image(&d, Version::Original) {
                    Ok((_, name)) => {
                        self.source_status = format!("OK: original E-mu {name} found and verified (SHA-256).");
                        self.data = Some(d);
                    }
                    Err(e) => {
                        self.source_status = format!("Not usable: {e}");
                        self.data = None;
                    }
                }
                self.source = Some(path);
            }
            Err(e) => self.source_status = format!("Cannot read file: {e}"),
        }
    }

    fn build(&mut self) -> Result<(), String> {
        let d = self.data.as_ref().ok_or("choose EOS470.EXE first")?;
        let (img, name) = eos_core::build_image(d, self.version)?;
        let msgs = filedump::messages_for_image(&img)?;
        self.log.push(format!(
            "Built {name}: {} MIDI messages, checksum {:08x}, verified by the loader simulation (~{:.0} min at MIDI speed).",
            msgs.len(),
            eos_core::image::csum(&img),
            msgs.iter().map(|m| m.len()).sum::<usize>() as f32 / 3125.0 / 60.0
        ));
        self.built = Some((msgs, name));
        Ok(())
    }

    fn start_send(&mut self) {
        let Some((msgs, name)) = self.built.clone() else { return };
        let (Some(out_name), Some(in_name)) = (self.outs.get(self.out_sel).cloned(), self.ins.get(self.in_sel).cloned())
        else {
            self.log.push("Choose a MIDI output and input.".into());
            return;
        };
        let stop = Arc::new(AtomicBool::new(false));
        let (tx, rx) = channel();
        let stop2 = stop.clone();
        std::thread::spawn(move || {
            let res = (|| -> Result<(), String> {
                let mut out = midi::open_output(&out_name)?;
                let (_conn, mrx) = midi::open_input(&in_name)?;
                let _ = tx.send(Msg::Log(format!(
                    "Sending {name} on '{out_name}' (replies from '{in_name}'). Now power on the E4 holding [Enter] and answer Yes to \"Download OS from MIDI?\"."
                )));
                sender::send(&mut out, &mrx, &msgs, Duration::from_secs(600), stop2, |p| {
                    let _ = match p {
                        sender::Progress::Waiting => tx.send(Msg::Log("Waiting for the E4 loader (up to 10 min)...".into())),
                        sender::Progress::Started => tx.send(Msg::Log("Loader answered, transferring...".into())),
                        sender::Progress::Packet(i, n) => tx.send(Msg::Progress(i as f32 / n as f32)),
                        sender::Progress::Retry(i, why) => tx.send(Msg::Log(format!("packet {i}: {why}, resent"))),
                        sender::Progress::Done => tx.send(Msg::Log(
                            "Done. The E4 verifies the image and asks \"Burn to flash?\": answer Yes and wait until it restarts.".into(),
                        )),
                        sender::Progress::Failed(e) => tx.send(Msg::Log(e)),
                    };
                })
            })();
            let _ = tx.send(Msg::Finished(res));
        });
        self.progress = 0.0;
        self.running = Some((stop, rx));
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        if let Some((_, rx)) = &self.running {
            let mut finished = None;
            while let Ok(m) = rx.try_recv() {
                match m {
                    Msg::Log(s) => self.log.push(s),
                    Msg::Progress(p) => self.progress = p,
                    Msg::Finished(r) => finished = Some(r),
                }
            }
            if let Some(r) = finished {
                if let Err(e) = r {
                    self.log.push(format!("Stopped: {e}"));
                }
                self.running = None;
            }
            ctx.request_repaint_after(Duration::from_millis(100));
        }
        let busy = self.running.is_some();
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("EOS Flasher — E-mu E4 Ultra, EOS 4.71-beta2 build 3");
            ui.label("Uses your own copy of E-mu's EOS470.EXE; no E-mu firmware is included in this app.");
            ui.separator();

            ui.strong("1. Firmware source");
            ui.horizontal(|ui| {
                if ui.add_enabled(!busy, egui::Button::new("Choose EOS470.EXE…")).clicked() {
                    if let Some(p) = rfd::FileDialog::new().add_filter("EOS470.EXE / floppy image", &["exe", "EXE", "img", "IMG"]).pick_file() {
                        self.load(p);
                    }
                }
                if let Some(p) = &self.source {
                    ui.monospace(p.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default());
                }
            });
            ui.label(&self.source_status);
            ui.separator();

            ui.strong("2. Version");
            ui.horizontal(|ui| {
                let before = self.version;
                ui.radio_value(&mut self.version, Version::LfoCk, "EOS 4.71-beta2 b3+LfoCk");
                ui.radio_value(&mut self.version, Version::Build3, "EOS 4.71-beta2 build 3 (latest)");
                ui.radio_value(&mut self.version, Version::Beta2, "Build 2");
                ui.radio_value(&mut self.version, Version::Beta1, "EOS 4.71-beta");
                ui.radio_value(&mut self.version, Version::Original, "Original EOS 4.70 (go back)");
                if before != self.version {
                    self.built = None;
                }
            });
            ui.horizontal(|ui| {
                if ui.add_enabled(!busy && self.data.is_some(), egui::Button::new("Build")).clicked() {
                    if let Err(e) = self.build() {
                        self.log.push(format!("Build failed: {e}"));
                    }
                }
                if ui.add_enabled(self.built.is_some(), egui::Button::new("Save .syx…")).clicked() {
                    if let Some((msgs, name)) = &self.built {
                        let file = format!("{}.syx", name.replace(' ', "_"));
                        if let Some(p) = rfd::FileDialog::new().set_file_name(&file).save_file() {
                            match std::fs::write(&p, filedump::to_syx(msgs)) {
                                Ok(_) => self.log.push(format!("Saved {}", p.display())),
                                Err(e) => self.log.push(format!("Save failed: {e}")),
                            }
                        }
                    }
                }
                if let Some((_, name)) = &self.built {
                    ui.label(format!("ready: {name}"));
                }
            });
            ui.separator();

            ui.strong("3. MIDI (the E4 must be connected both ways: the loader answers every packet)");
            ui.horizontal(|ui| {
                ui.label("Output to E4:");
                let prev = self.out_sel;
                egui::ComboBox::from_id_salt("out")
                    .width(260.0)
                    .selected_text(self.outs.get(self.out_sel).cloned().unwrap_or("(none)".into()))
                    .show_ui(ui, |ui| {
                        for (i, n) in self.outs.iter().enumerate() {
                            ui.selectable_value(&mut self.out_sel, i, n);
                        }
                    });
                if prev != self.out_sel {
                    self.match_input();
                }
                if ui.add_enabled(!busy, egui::Button::new("Refresh")).clicked() {
                    self.refresh_ports();
                }
            });
            ui.horizontal(|ui| {
                ui.label("Input from E4:");
                egui::ComboBox::from_id_salt("in")
                    .width(260.0)
                    .selected_text(self.ins.get(self.in_sel).cloned().unwrap_or("(none)".into()))
                    .show_ui(ui, |ui| {
                        for (i, n) in self.ins.iter().enumerate() {
                            ui.selectable_value(&mut self.in_sel, i, n);
                        }
                    });
            });
            ui.separator();

            ui.strong("4. Flash");
            ui.label("Press Send, then power on the E4 holding [Enter] and answer Yes to \"Download OS from MIDI?\". \
                      After the transfer (about 9 minutes) answer Yes to \"Burn to flash?\". Do not switch off while it burns.");
            ui.horizontal(|ui| {
                if !busy {
                    if ui.add_enabled(self.built.is_some(), egui::Button::new("Send to E4")).clicked() {
                        self.start_send();
                    }
                } else if ui.button("Cancel").clicked() {
                    if let Some((stop, _)) = &self.running {
                        stop.store(true, Ordering::Relaxed);
                    }
                }
                ui.add(egui::ProgressBar::new(self.progress).show_percentage());
            });
            ui.separator();
            egui::ScrollArea::vertical().stick_to_bottom(true).show(ui, |ui| {
                for l in &self.log {
                    ui.label(l);
                }
            });
        });
    }
}

fn main() -> eframe::Result<()> {
    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([720.0, 640.0]).with_title("EOS Flasher"),
        ..Default::default()
    };
    eframe::run_native("EOS Flasher", opts, Box::new(|_| Ok(Box::new(App::new()))))
}
