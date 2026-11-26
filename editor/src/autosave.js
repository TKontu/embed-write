// ED-05: autosave with atomic writes. Saved bytes are getMarkdown() output (I1).
// Unwired until the Tauri shell (AP-01) owns file I/O.
import { open, rename, unlink } from 'node:fs/promises';
import { dirname, basename, join } from 'node:path';
import { randomBytes } from 'node:crypto';

/** Write `text` to `path` atomically: temp file in same dir, fsync, rename, fsync dir. */
export async function atomicWrite(path, text) {
  const dir = dirname(path);
  const tmp = join(dir, `.${basename(path)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`);
  let fh;
  try {
    fh = await open(tmp, 'wx');
    await fh.writeFile(text, 'utf8');
    await fh.sync();
    await fh.close();
    fh = undefined;
    await rename(tmp, path);
  } catch (err) {
    if (fh) await fh.close().catch(() => {});
    await unlink(tmp).catch(() => {});
    throw err;
  }
  // Persist the rename; directory fsync is unsupported on some platforms (e.g. Windows).
  let dh;
  try {
    dh = await open(dir, 'r');
    await dh.sync();
  } catch { /* not supported */ } finally {
    if (dh) await dh.close().catch(() => {});
  }
}

/**
 * Debounced, serialized autosave.
 * @param {{ getMarkdown: () => string, write: (text: string) => Promise<void>, delayMs?: number }} opts
 */
export function createAutosave({ getMarkdown, write, delayMs = 1000 }) {
  let lastWritten;
  let timer = null;
  let chain = Promise.resolve();
  let disposed = false;

  const writeIfChanged = async () => {
    const text = getMarkdown();
    if (text === lastWritten) return;
    await write(text);
    lastWritten = text;
  };

  function flush() {
    if (timer) { clearTimeout(timer); timer = null; }
    const run = chain.then(writeIfChanged);
    chain = run.catch(() => {});
    return run;
  }

  function schedule() {
    if (disposed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = null; flush().catch(() => {}); }, delayMs);
  }

  function dispose() {
    disposed = true;
    if (timer) { clearTimeout(timer); timer = null; }
  }

  return { schedule, flush, dispose };
}
