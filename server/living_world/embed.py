"""Meaning search for memories: a small English sentence model turns each memory into 384 numbers, and memories whose
numbers point the same way are about the same thing.

The model is all-MiniLM-L6-v2 (sentence-transformers, Apache-2.0), its 23 MB 8-bit ONNX form, run on the CPU on one
thread. It needs onnxruntime, numpy and tokenizers, which Mantella's own exe already carries for its speech recognition,
so nothing extra is installed. The two files are looked for in the folders given to configure(): first the one shipped
with the Hub, then the user folder, where they are downloaded once (pinned revision, SHA-256 checked) when downloads are
allowed. Nothing here ever raises: until the model is ready, or if it cannot load, current() is None and every caller
uses keyword search instead."""
import hashlib
import logging
import os
import threading
import time
import urllib.request

logger = logging.getLogger('Mantella')

MODEL_ID = 'all-MiniLM-L6-v2/quint8_avx2'  # stored with each embedding: another model's numbers are made again
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
_BASE = f'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{REVISION}/'
MODEL_FILE = 'model_quint8_avx2.onnx'
TOKENIZER_FILE = 'tokenizer.json'
FILES = {  # name: (SHA-256, download URL)
    MODEL_FILE: ('b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21', _BASE + 'onnx/' + MODEL_FILE),
    TOKENIZER_FILE: ('be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037', _BASE + TOKENIZER_FILE),
}
DIM = 384
MAX_TOKENS = 256  # word pieces read per memory; a memory entry is at most about this long
DOWNLOAD_TIMEOUT = 60
CACHE_SIZE = 64  # recent query texts kept with their numbers, so a prompt built again costs nothing
LOAD_TIMEOUT = 120  # seconds: a load still not done by then (its thread died without a word) may be started again

_state = {'engine': None, 'folders': [], 'download': False, 'started': False, 'failed': '', 'started_at': 0.0}
_lock = threading.Lock()


class Engine:
    """The loaded model. embed(texts) -> list of unit-length float32 vectors, or None if the run failed."""

    def __init__(self, folder: str):
        import numpy
        import onnxruntime
        import tokenizers
        self.np = numpy
        self.tokenizer = tokenizers.Tokenizer.from_file(os.path.join(folder, TOKENIZER_FILE))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding(pad_id=0, pad_token='[PAD]')  # to the longest in each batch, not a fixed 128
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1  # never takes CPU from the game
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.session = onnxruntime.InferenceSession(os.path.join(folder, MODEL_FILE), options, providers=['CPUExecutionProvider'])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.cache: dict = {}
        self.cache_lock = threading.Lock()  # prompt builds, archive syncs and recalls embed on different threads
        self.run_lock = threading.Lock()

    def _cached(self, text: str):
        with self.cache_lock:
            return self.cache.get(text)

    def _remember(self, text: str, vector) -> None:
        with self.cache_lock:
            while len(self.cache) >= CACHE_SIZE:
                self.cache.pop(next(iter(self.cache)))
            self.cache[text] = vector

    def embed(self, texts: list[str]):
        np = self.np
        out, todo = {}, []
        for text in texts:
            vector = self._cached(text)
            if vector is not None:
                out[text] = vector
            elif text not in todo:
                todo.append(text)
        for start in range(0, len(todo), 16):
            batch = todo[start:start + 16]
            encoded = self.tokenizer.encode_batch([t or ' ' for t in batch])
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            feed = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': np.zeros_like(ids)}
            with self.run_lock:
                hidden = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0]
            # the sentence is the average of its word pieces (padding left out), scaled to length 1
            weights = mask[:, :, None].astype(np.float32)
            pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
            pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
            for text, vector in zip(batch, pooled.astype(np.float32)):
                out[text] = vector
                if len(texts) == 1:  # only queries are cached; memories are embedded once and stored
                    self._remember(text, vector)
        return [out[t] for t in texts]


def configure(folders: list[str], download: bool) -> None:
    """Where the model may be (in order) and whether it may be downloaded into the last folder."""
    _state['folders'] = [f for f in folders if f]
    _state['download'] = bool(download)


def current():
    """The ready model, or None. The first call starts loading it in the background (again if a load got stuck)."""
    if _state['engine'] is None and _state['folders'] and not _state['failed']:
        start()
    return _state['engine']


def use(engine) -> None:
    """Puts an engine in place directly (tests, or None to switch meaning search off)."""
    _state['engine'] = engine
    _state['started'] = True


def status() -> str:
    if _state['engine'] is not None:
        return 'ready'
    return _state['failed'] or ('loading' if _state['started'] else 'off')


def start() -> threading.Thread | None:
    """Loads the model in the background, once; again only when an earlier load is still not done after LOAD_TIMEOUT."""
    with _lock:
        if _state['started']:
            stuck = (_state['engine'] is None and not _state['failed'] and _state['started_at'] > 0
                     and time.time() - _state['started_at'] > LOAD_TIMEOUT)
            if not stuck:
                return None
            logger.warning("Living World: the memory search model is still not loaded after two minutes; trying again")
        _state['started'] = True
        _state['started_at'] = time.time()
    thread = threading.Thread(target=_load, name='living-world-memory-model', daemon=True)
    thread.start()
    return thread


def file_ok(path: str, sha256: str) -> bool:
    try:
        digest = hashlib.sha256()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                digest.update(block)
        return digest.hexdigest() == sha256
    except OSError:
        return False


def find_folder(folders: list[str]) -> str | None:
    """The first folder holding both files, each with the expected SHA-256."""
    for folder in folders:
        if all(file_ok(os.path.join(folder, name), sha) for name, (sha, _) in FILES.items()):
            return folder
    return None


def download(folder: str, opener=urllib.request.urlopen) -> bool:
    """Fetches the files into folder; each is written beside its final name and only moved there once its SHA-256
    matches, so a broken or cut-off download is never used."""
    os.makedirs(folder, exist_ok=True)
    for name, (sha, url) in FILES.items():
        path = os.path.join(folder, name)
        if file_ok(path, sha):
            continue
        tmp = path + '.download'
        try:
            with opener(url, timeout=DOWNLOAD_TIMEOUT) as response, open(tmp, 'wb') as f:
                for block in iter(lambda: response.read(1 << 20), b''):
                    f.write(block)
            if not file_ok(tmp, sha):
                logger.warning(f"Living World: the downloaded {name} did not match its checksum; not used")
                os.remove(tmp)
                return False
            os.replace(tmp, path)
        except Exception as e:
            logger.warning(f"Living World: could not download {name} for memory search ({e}); keyword search is used")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
    return True


def _load() -> None:
    """Each step is logged, so a load that never ends shows where it stopped."""
    try:
        logger.info(f"Living World: loading the memory search model (looking in {len(_state['folders'])} folder(s))")
        folder = find_folder(_state['folders'])
        if folder is None and _state['download'] and _state['folders']:
            logger.info("Living World: memory search model not found; downloading it")
            if download(_state['folders'][-1]):
                folder = find_folder(_state['folders'][-1:])
        if folder is None:
            _state['failed'] = 'no model'
            logger.info("Living World: no memory search model found; old memories are found by keywords")
            return
        logger.info(f"Living World: memory search model files found in {folder}; starting it")
        _state['engine'] = Engine(folder)
        logger.info(f"Living World: memory search model loaded from {folder}")
    except BaseException as e:  # no onnxruntime, numpy or tokenizers in this exe, a broken model file, or worse
        _state['failed'] = f'could not load ({type(e).__name__}: {e})'
        logger.warning(f"Living World: the memory search model could not load ({type(e).__name__}: {e}); old memories are "
                       f"found by keywords")
