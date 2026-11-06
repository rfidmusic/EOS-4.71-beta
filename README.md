# EOS 4.71-beta2 b3+LfoCk for the E-mu E4 Ultra

An unofficial update of E-mu's **EOS 4.70** for the Emulator IV family **Ultra** models, made by reverse
engineering the 4.70 firmware and testing every change in an emulator and on a real E4 Ultra.

**What's new** (details in [CHANGELOG.md](CHANGELOG.md) and the
[EOS 4.71-beta2 Operation Manual Addendum](docs/EOS-4.71-beta-Addendum.md),
[PDF](docs/EOS-4.71-beta-Addendum.pdf)):

**New in b3+LfoCk:** **Lfo1Ck** and **Lfo2Ck** cord destinations. A negative amount selects that LFO's tempo
division and overrides Rate; the Rate field shows the division and is grey while the cord holds it. The startup
screen shows **EOS 4.71-beta2 b3+LfoCk**. Build 3 stays available in EOS Flasher.

**New in build 3:** E-mu's own filters are back (after multiple tests and retuning, the OB-Xa filter models
offered too little at too much cost), and five **Fuzz filters** join the end of the filter list: 2 Pole LP+Fuzz,
4 Pole LP+Fuzz (unchanged), 2nd Ord HP+Fuzz, 2nd Ord BP+Fuzz and Contrary BP+Fuzz. **Be mindful of gain: the
Fuzz filters get LOUD.** Presets from the earlier betas that used the OB-Xa models now play E-mu's filters. See
the [CHANGELOG](CHANGELOG.md).

**New in 4.71-beta2:**

- **4 Pole LP+Fuzz** filter: a 4-pole ladder driven into the filter chip's overload (Q = fuzz).
- **Beat Munger Slice**: turns a drum loop into one sample per hit and a preset with each slice on its own key
  (cuts placed just before each hit, snapped to a zero crossing).
- **'Slice** cord destination: plays equal slices of one sample, one per key.
- **Insert Silence** in Sample Edit: 4 samples of silence, the lead-in loops and wavetables need.
- **WTScan** (renamed from SLpScn): notes start at the loop, fast moves glide instead of bursting.
- **Balanced pan centre** (4.70 and 4.71-beta were about 0.24 dB right-heavy).

**New in build 2:** the 4 Pole LP+Fuzz level follows Q smoothly. (Build 2's high-pass level trim belonged to the
OB-Xa models and is gone with them in build 3.)

**From 4.71-beta:**

- **OB-Xa (CEM3320) filter models** (4.71-beta to build 2; build 3 returns to E-mu's own filters and uses the
  OB-Xa models only inside the Fuzz filters).
- **Tempo-synced LFOs** (4 bars … 1/32, Key Sync or Free Run) and a new **saw down** LFO shape.
- **Transwave scanning**: new cord destination **WTScan** (SLpScn in 4.71-beta) moves the sample loop through a wavetable
  ([sample guide](docs/transwave-guide.md)).
- **MIDI clock** that keeps LFOs, clock sources, arpeggiator and Beats running when your DAW stops, and
  no longer runs double speed with an external clock.
- **Pan bug fixed**: voice Pan, Multimode Pan and MIDI CC10 now use their full range (4.70 hits hard
  left/right at half range).
- **Faster cord processing** (sound-identical).

> EOS 4.71-beta2 is not made, supported or endorsed by E-mu Systems or Creative Technology. It is a beta:
> back up your banks first. You can always flash the original EOS 4.70 back.

## Get it

E-mu's firmware is not distributed here. The **EOS Flasher** app builds 4.71-beta2 build 3 (or b3+LfoCk, build 2, or the
earlier 4.71-beta) from your own copy of
E-mu's update file **EOS470.EXE** (it verifies the file is the original 4.70, applies this project's
patch and verifies the result) and sends it to the E4 over MIDI.

Downloads (see [Releases](../../releases)):

| App | macOS 11+ (universal: Apple silicon + Intel) | macOS 10.13 High Sierra+ (Intel) | Windows | Linux (Flatpak, x86_64) |
|---|---|---|---|---|
| **EOS Flasher**: build 4.71-beta2 build 3 (or b3+LfoCk, build 2, 4.71-beta, or the original 4.70) and flash it over MIDI | `EOS-Flasher-macOS-universal.zip` | `EOS-Flasher-macOS-HighSierra-Intel.zip` | `EOS-Flasher-Windows.zip` | `EOS-Flasher-Linux-x86_64.flatpak` |
| **EOS Pan Test**: measure the pan bug on your E4 and report results | `EOS-PanTest-macOS-universal.zip` | `EOS-PanTest-macOS-HighSierra-Intel.zip` | `EOS-PanTest-Windows.zip` | `EOS-PanTest-Linux-x86_64.flatpak` |

The apps are not signed with an Apple or Microsoft developer certificate, so the first launch needs one extra
step. On an Intel Mac with macOS 10.13–10.15 use the High Sierra builds; on macOS 11 or later (and on Apple
silicon) use the universal ones.

**macOS: "EOS Flasher" Not Opened / "Apple could not verify … is free of malware"**

macOS shows this the first time you open an app that isn't from the App Store or a registered developer. Click
**Done** (not **Move to Trash**), then:

- **macOS 15 Sequoia and later:**
  1. Open **System Settings → Privacy & Security**.
  2. Scroll down to **Security**: it says "EOS Flasher" was blocked. Click **Open Anyway**.
  3. Confirm with your password or Touch ID, then click **Open Anyway** in the dialog that follows.
- **macOS 10.13 High Sierra to 14 Sonoma:** Control-click (or right-click) the app, choose **Open**, then click
  **Open** in the dialog.

You only need to do this once per app: once for EOS Flasher and once for EOS Pan Test. Alternatively, in Terminal
(adjust the path to where you put the app):

```bash
xattr -dr com.apple.quarantine "/Applications/EOS Flasher.app"
```

**Windows:** if SmartScreen says "Windows protected your PC", choose **More info → Run anyway**.

On Linux, install the Freedesktop runtime once, then the bundle (MIDI uses the ALSA sequencer):

```bash
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.freedesktop.Platform//24.08
flatpak install --user EOS-Flasher-Linux-x86_64.flatpak
flatpak run io.github.rfidmusic.EOSFlasher
```

### Flash EOS 4.71-beta2

1. Connect a MIDI interface **both ways** to the E4 (the loader acknowledges every packet).
2. Start **EOS Flasher**, choose your **EOS470.EXE**, select **EOS 4.71-beta2 build 3**, press **Build**.
3. Select the MIDI output and input, press **Send to E4**.
4. Power on the E4 holding **Enter**, answer **Yes** to "Download OS from MIDI?".
5. After about 9 minutes answer **Yes** to "Burn to flash?". The startup screen shows **EOS 4.71-beta2 build 3**.

To go back, do the same with **Original EOS 4.70**.

### Test the pan bug (and send a report)

1. **Download the test bank** [`testbank/Test Suite.E4B`](testbank/Test%20Suite.E4B) and load it into your
   E4. The pan test uses **preset 000** (one sine voice on key 72); see [testbank/README.md](testbank/README.md).
2. Connect MIDI both ways and the E4's main outputs (optionally sub outputs) to your audio interface.
3. Start **EOS Pan Test**, select the MIDI ports, the E4's device ID and channel, the audio device and the
   input pair(s), and press **Run tests**.
4. The summary says whether the pan bug is present ("hard left/right at half range") or fixed
   ("full pan range"), and whether the centre is balanced (4.71-beta2). **Save CSV + WAV** keeps the data; **Report to GitHub** opens a pre-filled
   [Pan test report](../../issues/new?template=pan-test-report.md) issue in your browser for you to
   review and submit (attach the CSV/WAV if you like).

### RFX-32 owners: the RFX stuck pan test (build 4)

Old reports say that with an RFX-32 fitted, a note can start at, or stay at, the pan an earlier note on the same
channel had. To help find the cause:

1. Flash **EOS 4.71-beta2 build 4** with EOS Flasher.
2. Load the [test bank](testbank/README.md). In **EOS Pan Test**, tick **RFX stuck pan** and set Voices to 64 or 128.
   The test plays preset 004 (sine on every key). Optionally, set Stereo preset to 001 to add a mono-after-stereo
   phase. Keep the RFX buses empty or bypassed so only the dry voice
   reaches Main.
3. Run the test, press **Save CSV + WAV**, then **Report to GitHub**.
4. Submit the issue that opens, and drag the saved folder (zipped) into it.

Results only reach us as a GitHub issue, so please submit one even if nothing went wrong.

## Repository

| Path | Contents |
|---|---|
| `apps/` | Rust apps: `eos-flasher`, `eos-pantest`, shared `eos-core` (codec, patch, MIDI File Dump, editor SysEx) |
| `apps/eos-core/data/eos471b3lfock.e4p` | Build 3 plus Lfo1Ck / Lfo2Ck. Startup name `EOS 4.71-beta2 b3+LfoCk` |
| `apps/eos-core/data/eos471beta2b3.e4p` | The build 3 patch: the 6,597 bytes this project wrote, plus steps that copy E-mu code it moves within your own 4.70 |
| `apps/eos-core/data/eos471beta2.e4p` | The build 2 patch: only the 7,165 bytes this project wrote, applied to your own 4.70 |
| `apps/eos-core/data/eos471beta.e4p` | The 4.71-beta patch (3,232 bytes) |
| `patches/` | Assembler sources (ColdFire) of every change |
| `tools/` | Python builders, emulator test suites, hardware test scripts, MIDI File Dump tool |
| `notes/` | Design notes and measurements for each feature |
| `docs/` | Manual addendum (Markdown + PDF), Transwave guide, technical reference |
| `testbank/` | Test Suite.E4B bank |
| `testsignals/` | Test sine/sweep signals and the example wavetable |

Building the apps: `cd apps && cargo build --release` (macOS universal bundles: `apps/bundle_macos.sh`;
High Sierra Intel bundles: `apps/bundle_macos_highsierra.sh`; Flatpak manifests: `apps/linux/`).
Rebuilding the firmware from source needs the stock image from your EOS470.EXE; see
[docs/TECHNICAL.md](docs/TECHNICAL.md).

## License

MIT for the code, patches and documentation in this repository ([LICENSE](LICENSE)). E-mu's EOS
firmware is not included and remains the property of its owners.
