//! E-mu EOS (Emulator IV family, EOS 4.70) support library.
//!
//! * [`lz`]       floppy/MIDI Lz77 codec of the EOS Primary Loader (PL01 01f05, routine 0x18BE8)
//! * [`image`]    OS image header and checksum
//! * [`exe`]      locate the EOS floppy image inside E-mu's self-extracting EOS470.EXE
//! * [`patch`]    the EOS 4.71-beta and 4.71-beta2 patches (only our bytes, plus copies within the user's own 4.70)
//! * [`filedump`] MMA "MIDI File Dump" messages as accepted by the loader, plus a loader simulation
//! * [`sender`]   handshaked transfer to the sampler (MIDI output and input)
//! * [`remote`]   E-mu editor SysEx: set and read parameters of a running EOS
//! * [`midi`]     MIDI port listing and connection helpers (midir)

pub mod exe;
pub mod filedump;
pub mod image;
pub mod lz;
pub mod midi;
pub mod patch;
pub mod remote;
pub mod testsound;
pub mod sender;

/// Builds an OS image ready to send from E-mu's EOS470.EXE (or a raw EOS floppy image): the stock
/// 4.70 image, or it patched to `version`. Returns (image, header name).
pub fn build_image(exe_or_floppy: &[u8], version: patch::Version) -> Result<(Vec<u8>, String), String> {
    let floppy = exe::find_floppy(exe_or_floppy).ok_or("no EOS floppy image found in this file")?;
    let stock = image::unpack_floppy(floppy)?;
    patch::check_stock(&stock)?;
    let img = match version.patch() {
        Some(p) => patch::apply(&stock, p)?,
        None => stock,
    };
    let name = image::name(&img);
    Ok((img, name))
}
