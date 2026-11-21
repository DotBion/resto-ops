// Fix-It Cam client helpers: shrink big phone videos in the browser, upload with progress.
(function(){
const MB = 1024*1024;
const SHRINK_OVER = 15*MB, MAX_SECONDS = 15, TARGET_H = 720, BITRATE = 2_000_000, N_FRAMES = 8;

function pickMime(){
  if (!window.MediaRecorder) return null;
  const c = ['video/mp4;codecs=avc1','video/mp4','video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'];
  for (const m of c) { try { if (MediaRecorder.isTypeSupported(m)) return m } catch(e){} }
  return null;
}

function loadVideo(file){
  return new Promise((res, rej) => {
    const v = document.createElement('video');
    v.playsInline = true; v.setAttribute('playsinline',''); v.preload = 'auto'; v.muted = true;
    v.style.cssText = 'position:fixed;left:-10px;top:-10px;width:2px;height:2px;opacity:0;pointer-events:none';
    document.body.appendChild(v);
    v.src = URL.createObjectURL(file);
    const t = setTimeout(() => rej(new Error('Could not read this video in the browser')), 20000);
    v.onloadedmetadata = () => { clearTimeout(t); res(v) };
    v.onerror = () => { clearTimeout(t); rej(new Error('Browser cannot decode this video')) };
  });
}
function cleanup(v){ try{ URL.revokeObjectURL(v.src); v.remove() }catch(e){} }
function canvasFor(v){
  const scale = Math.min(1, TARGET_H / Math.min(v.videoWidth, v.videoHeight) );
  const c = document.createElement('canvas');
  c.width = Math.round(v.videoWidth*scale/2)*2; c.height = Math.round(v.videoHeight*scale/2)*2;
  return c;
}

async function reencode(file, onStatus){
  const mime = pickMime();
  const v = await loadVideo(file);
  try {
    const c = canvasFor(v);
    if (!mime || !c.captureStream) throw new Error('no-recorder');
    const ctx = c.getContext('2d');
    const stream = c.captureStream(30);
    // try to keep audio (people say model numbers out loud)
    let actx = null;
    try {
      actx = new (window.AudioContext || window.webkitAudioContext)();
      const src = actx.createMediaElementSource(v);
      const dest = actx.createMediaStreamDestination();
      src.connect(dest);           // not connected to speakers: silent for the user
      dest.stream.getAudioTracks().forEach(t => stream.addTrack(t));
      v.muted = false;
    } catch(e) { v.muted = true }
    const rec = new MediaRecorder(stream, {mimeType: mime, videoBitsPerSecond: BITRATE});
    const chunks = [];
    rec.ondataavailable = e => e.data && e.data.size && chunks.push(e.data);
    const done = new Promise(r => rec.onstop = r);
    const dur = Math.min(v.duration || MAX_SECONDS, MAX_SECONDS);
    v.currentTime = 0;
    try { await v.play() } catch(e) { v.muted = true; await v.play() }
    rec.start(500);
    await new Promise(resolve => {
      const draw = () => {
        ctx.drawImage(v, 0, 0, c.width, c.height);
        onStatus && onStatus(`Shrinking video… ${Math.min(100, Math.round(100*v.currentTime/dur))}%`);
        if (v.currentTime >= dur || v.ended) return resolve();
        if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(draw); else requestAnimationFrame(draw);
      };
      draw();
      v.onended = resolve;
      setTimeout(resolve, (dur + 5) * 1000);
    });
    v.pause(); rec.stop(); await done;
    if (actx) actx.close();
    const type = mime.split(';')[0];
    const blob = new Blob(chunks, {type});
    if (blob.size < 20*1024) throw new Error('recording empty');
    const ext = type.includes('mp4') ? 'mp4' : 'webm';
    return [new File([blob], `clip-shrunk.${ext}`, {type})];
  } finally { cleanup(v) }
}

async function keyframes(file, onStatus){
  const v = await loadVideo(file);
  try {
    const c = canvasFor(v), ctx = c.getContext('2d');
    const dur = Math.min(v.duration || 1, 60);
    const out = [];
    for (let i = 0; i < N_FRAMES; i++) {
      const t = dur * (i + 0.5) / N_FRAMES;
      await new Promise((res) => { v.onseeked = res; v.currentTime = t; setTimeout(res, 4000) });
      ctx.drawImage(v, 0, 0, c.width, c.height);
      const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.82));
      if (blob) out.push(new File([blob], `frame_${String(i).padStart(2,'0')}_t${t.toFixed(1)}s.jpg`, {type:'image/jpeg'}));
      onStatus && onStatus(`Extracting keyframes… ${i+1}/${N_FRAMES}`);
    }
    if (!out.length) throw new Error('Could not extract frames');
    return out;
  } finally { cleanup(v) }
}

// Returns {files:[File], mode:'original'|'reencoded'|'frames'}
async function prepare(file, onStatus, {allowFrames = true} = {}){
  if (!file.type.startsWith('video/') || file.size <= SHRINK_OVER) return {files:[file], mode:'original'};
  try { return {files: await reencode(file, onStatus), mode:'reencoded'} }
  catch(e) { console.warn('re-encode failed:', e) }
  if (allowFrames) {
    try { return {files: await keyframes(file, onStatus), mode:'frames'} }
    catch(e) { console.warn('keyframes failed:', e) }
  }
  return {files:[file], mode:'original'};
}

// XHR upload with progress. onProgress(sentBytes,totalBytes); onChunk(newText) for streamed responses.
function upload(url, formData, {onProgress, onChunk, timeoutMs = 10*60*1000} = {}){
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    let seen = 0;
    x.open('POST', url);
    x.timeout = timeoutMs;
    x.upload.onprogress = e => onProgress && onProgress(e.loaded, e.lengthComputable ? e.total : 0);
    x.onprogress = () => { if (onChunk) { const t = x.responseText.slice(seen); seen = x.responseText.length; if (t) onChunk(t) } };
    x.onload = () => {
      if (onChunk) { const t = x.responseText.slice(seen); seen = x.responseText.length; if (t) onChunk(t) }
      if (x.status >= 200 && x.status < 300) resolve(x.responseText);
      else { let m = 'Server error ' + x.status; try { m = JSON.parse(x.responseText).detail || m } catch(e){} reject(new Error(m)) }
    };
    x.onerror = () => reject(new Error('Upload failed: network error. Check Wi-Fi, or try a shorter clip (5–10 s).'));
    x.ontimeout = () => reject(new Error('Upload timed out. Try a shorter clip (5–10 s) or better Wi-Fi.'));
    x.send(formData);
  });
}

const fmtMB = b => (b/MB).toFixed(b < 10*MB ? 1 : 0) + ' MB';
window.FixItUpload = {prepare, upload, fmtMB, SHRINK_OVER};
})();
