/* Tag writers for FLAC (Vorbis comment + PICTURE) and MP3 (ID3v2.3).
 * Operates on ArrayBuffers so the result can be wrapped in a Blob and
 * handed to browser.downloads.download via blob:URL.
 */

const VENDOR = "qobuz-downloader";

// ---------- shared helpers ----------
function utf8(s) {
  return new TextEncoder().encode(String(s ?? ""));
}

function concat(chunks) {
  let n = 0;
  for (const c of chunks) n += c.byteLength;
  const out = new Uint8Array(n);
  let o = 0;
  for (const c of chunks) {
    out.set(c instanceof Uint8Array ? c : new Uint8Array(c), o);
    o += c.byteLength;
  }
  return out;
}

function u32be(n) {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setUint32(0, n >>> 0, false);
  return b;
}

function u32le(n) {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setUint32(0, n >>> 0, true);
  return b;
}

// ---------- FLAC ----------
// FLAC stream = "fLaC" + metadata blocks + audio frames.
// Block header: 1 byte = (lastFlag<<7) | (type & 0x7F),
//               3 bytes BE = data length.
// Block types: 0=STREAMINFO (mandatory, must be first), 4=VORBIS_COMMENT,
//              6=PICTURE.

function buildVorbisComment(tags) {
  // tags is { FIELD: value | [values] }
  const vendor = utf8(VENDOR);
  const lines = [];
  for (const [k, v] of Object.entries(tags)) {
    if (v == null || v === "") continue;
    const values = Array.isArray(v) ? v : [v];
    for (const val of values) {
      if (val == null || val === "") continue;
      lines.push(utf8(`${k}=${val}`));
    }
  }
  const parts = [u32le(vendor.length), vendor, u32le(lines.length)];
  for (const line of lines) {
    parts.push(u32le(line.length));
    parts.push(line);
  }
  return concat(parts);
}

function buildPictureBlock(mime, descr, imgBytes, width, height) {
  // PICTURE block payload (FLAC spec, all big-endian):
  //   u32 picture type (3 = front cover)
  //   u32 mime length, mime ASCII
  //   u32 description length, description UTF-8
  //   u32 width, u32 height, u32 colour depth (bits/px), u32 colours-used (0 = non-indexed)
  //   u32 data length, data
  const mimeBytes = utf8(mime);
  const descrBytes = utf8(descr || "");
  return concat([
    u32be(3),
    u32be(mimeBytes.length), mimeBytes,
    u32be(descrBytes.length), descrBytes,
    u32be(width || 0), u32be(height || 0), u32be(24), u32be(0),
    u32be(imgBytes.length), imgBytes,
  ]);
}

function makeBlockHeader(type, length, last) {
  const h = new Uint8Array(4);
  h[0] = (last ? 0x80 : 0x00) | (type & 0x7F);
  h[1] = (length >> 16) & 0xFF;
  h[2] = (length >> 8) & 0xFF;
  h[3] = length & 0xFF;
  return h;
}

function rewriteFlac(buf, tags, picture /* { mime, bytes, width, height } | null */) {
  const u8 = new Uint8Array(buf);
  if (
    u8.length < 4 ||
    u8[0] !== 0x66 || u8[1] !== 0x4C || u8[2] !== 0x61 || u8[3] !== 0x43
  ) {
    throw new Error("FLAC: missing 'fLaC' magic");
  }

  let pos = 4;
  let streaminfo = null;
  // Skip past all existing metadata blocks. We keep STREAMINFO and drop the rest;
  // we'll write our own VORBIS_COMMENT (+ PICTURE) and append the audio frames.
  while (pos < u8.length) {
    const header = u8.subarray(pos, pos + 4);
    const last = (header[0] & 0x80) !== 0;
    const type = header[0] & 0x7F;
    const len = (header[1] << 16) | (header[2] << 8) | header[3];
    const blockStart = pos + 4;
    const blockEnd = blockStart + len;
    if (type === 0) {
      streaminfo = u8.subarray(blockStart, blockEnd);
    }
    pos = blockEnd;
    if (last) break;
  }
  if (!streaminfo) throw new Error("FLAC: no STREAMINFO block");
  const audio = u8.subarray(pos);

  const newBlocks = [];
  // STREAMINFO (not last)
  newBlocks.push(makeBlockHeader(0, streaminfo.length, false));
  newBlocks.push(streaminfo);

  // VORBIS_COMMENT
  const vc = buildVorbisComment(tags);
  const vcLast = !picture;
  newBlocks.push(makeBlockHeader(4, vc.length, vcLast));
  newBlocks.push(vc);

  // PICTURE (last, if present)
  if (picture) {
    const pic = buildPictureBlock(
      picture.mime, "Front Cover", picture.bytes, picture.width, picture.height
    );
    newBlocks.push(makeBlockHeader(6, pic.length, true));
    newBlocks.push(pic);
  }

  newBlocks.push(audio);
  return concat([new Uint8Array([0x66, 0x4C, 0x61, 0x43]), ...newBlocks]);
}

// ---------- MP3 / ID3v2.3 ----------
// Synchsafe (7 bits per byte, MSB always 0). Used by tag header size only.
function synchsafe(n) {
  return new Uint8Array([
    (n >> 21) & 0x7F,
    (n >> 14) & 0x7F,
    (n >>  7) & 0x7F,
    n         & 0x7F,
  ]);
}

function id3TextFrame(id, text) {
  if (text == null || text === "") return null;
  const body = concat([new Uint8Array([0x03]), utf8(text)]); // 0x03 = UTF-8
  return concat([
    utf8(id),                   // 4-byte frame id (ASCII)
    u32be(body.length),         // size (NOT synchsafe in v2.3)
    new Uint8Array([0x00, 0x00]), // flags
    body,
  ]);
}

function id3PictureFrame(mime, imgBytes) {
  // APIC: encoding(1) + mime(text)\0 + picture type(1) + description(text)\0 + image
  const body = concat([
    new Uint8Array([0x03]),     // UTF-8
    utf8(mime), new Uint8Array([0x00]),
    new Uint8Array([0x03]),     // 0x03 = front cover
    new Uint8Array([0x00]),     // empty description (UTF-8 terminator: single 0)
    imgBytes,
  ]);
  return concat([
    utf8("APIC"),
    u32be(body.length),
    new Uint8Array([0x00, 0x00]),
    body,
  ]);
}

function stripExistingId3v2(u8) {
  if (u8.length < 10) return u8;
  if (u8[0] !== 0x49 || u8[1] !== 0x44 || u8[2] !== 0x33) return u8; // "ID3"
  const size =
    ((u8[6] & 0x7F) << 21) |
    ((u8[7] & 0x7F) << 14) |
    ((u8[8] & 0x7F) <<  7) |
     (u8[9] & 0x7F);
  return u8.subarray(10 + size);
}

function rewriteMp3(buf, tags, picture) {
  const u8 = new Uint8Array(buf);
  const audio = stripExistingId3v2(u8);

  const frames = [
    id3TextFrame("TIT2", tags.TITLE),
    id3TextFrame("TPE1", tags.ARTIST),
    id3TextFrame("TALB", tags.ALBUM),
    id3TextFrame("TPE2", tags.ALBUMARTIST),
    id3TextFrame("TYER", tags.DATE ? String(tags.DATE).slice(0, 4) : null),
    id3TextFrame("TDRC", tags.DATE),
    id3TextFrame("TRCK", tags.TRACKNUMBER && tags.TRACKTOTAL
      ? `${tags.TRACKNUMBER}/${tags.TRACKTOTAL}`
      : tags.TRACKNUMBER || null),
    id3TextFrame("TPOS", tags.DISCNUMBER && tags.DISCTOTAL
      ? `${tags.DISCNUMBER}/${tags.DISCTOTAL}`
      : tags.DISCNUMBER || null),
    id3TextFrame("TCON", tags.GENRE),
    id3TextFrame("TCOM", tags.COMPOSER),
    id3TextFrame("TSRC", tags.ISRC),
    id3TextFrame("TCOP", tags.COPYRIGHT),
  ].filter(Boolean);

  if (picture) frames.push(id3PictureFrame(picture.mime, picture.bytes));

  const body = concat(frames);
  const header = concat([
    utf8("ID3"),
    new Uint8Array([0x03, 0x00]), // v2.3.0
    new Uint8Array([0x00]),       // flags
    synchsafe(body.length),
  ]);
  return concat([header, body, audio]);
}

// ---------- public ----------
self.tagger = {
  rewriteFlac,
  rewriteMp3,
};
