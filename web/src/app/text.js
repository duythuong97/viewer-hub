// Text helpers for pages that show or search Japanese (and other non-ASCII) text. Part of "@vh/ui".

/** For matching what a person types: NFKC (half-width ｶﾀｶﾅ → カタカナ, full-width ＡＢＣ１ → ABC1) then lower case.
 * Compare fold(query) against fold(text), like the Python SDK's fold(). */
export function fold(text) {
  return String(text ?? "").normalize("NFKC").toLowerCase();
}

/** A picked File as a JSON body: { content } when it is UTF-8, else { base64 } of its raw bytes (Shift_JIS, EUC-JP,
 * UTF-16…), so the addon decodes it (Python SDK decode_text) instead of the browser guessing UTF-8 and losing it. */
export async function readFileBody(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  try {
    return { content: new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes) };
  } catch {
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return { base64: btoa(binary) };
  }
}
