// Highlights: tap a card, and the camera flies from the whole state down to a
// few interesting wells while the color view changes and short captions explain
// what you are seeing. When it ends you are left in the live viewer to explore.
//
// app.js passes a small API (installHighlights below). This module never edits
// geometry; it only moves the camera, switches color modes and selects a well,
// the same things a visitor can do by hand.
import {HIGHLIGHTS, TIMING, findHighlight, regionalBounds, easeInOut, interpolatePose, datasetCounts} from './highlights-model.js';

const $ = id => document.getElementById(id);
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

export function installHighlights(api) {
  let run = 0, active = null;

  // ------------------------------------------------------------ UI
  const open = document.createElement('button');
  open.id = 'highlightsOpen'; open.type = 'button'; open.className = 'highlights-open';
  open.textContent = 'Highlights'; open.disabled = true;
  open.setAttribute('aria-haspopup', 'dialog'); open.setAttribute('aria-controls', 'highlightsPanel');
  document.querySelector('.header-actions')?.prepend(open);

  const panel = document.createElement('section');
  panel.id = 'highlightsPanel'; panel.className = 'highlights-panel'; panel.hidden = true;
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-labelledby', 'highlightsHeading');
  panel.innerHTML = `<div class="highlights-head"><h2 id="highlightsHeading">Highlights</h2>
    <button type="button" class="highlights-close" aria-label="Close highlights">×</button></div>
    <p class="caption">Short guided flights to interesting wells. Tap one, sit back, then explore from where it lands.</p>
    <div class="highlights-cards"></div>`;
  const cards = panel.querySelector('.highlights-cards');
  for (const h of HIGHLIGHTS) {
    const card = document.createElement('button');
    card.type = 'button'; card.className = 'highlight-card'; card.dataset.highlight = h.id;
    card.innerHTML = `<span class="eyebrow"></span><strong></strong><span></span>`;
    card.children[0].textContent = h.place.toUpperCase();
    card.children[1].textContent = h.title;
    card.children[2].textContent = h.teaser;
    card.onclick = () => start(h.id);
    cards.append(card);
  }

  const caption = document.createElement('div');
  caption.id = 'highlightCaption'; caption.className = 'highlight-caption'; caption.hidden = true;
  caption.innerHTML = `<div class="highlight-progress"><span></span><span></span><span></span></div>
    <p class="highlight-text" role="status" aria-live="polite"></p>
    <div class="highlight-actions"><button type="button" class="highlight-skip">Skip</button>
    <button type="button" class="highlight-next">Next highlight</button>
    <a class="highlight-tour button" hidden>Read the full tour</a>
    <button type="button" class="highlight-done primary" hidden>Explore</button></div>`;
  const viewport = $('viewport'), canvasHost = $('canvasHost');
  viewport.append(panel, caption);
  const text = caption.querySelector('.highlight-text'), dots = [...caption.querySelectorAll('.highlight-progress span')];
  const skip = caption.querySelector('.highlight-skip'), next = caption.querySelector('.highlight-next');
  const tourLink = caption.querySelector('.highlight-tour'), done = caption.querySelector('.highlight-done');

  open.onclick = () => { if (panel.hidden) showPanel(); else hidePanel(); };
  panel.querySelector('.highlights-close').onclick = hidePanel;
  skip.onclick = () => { if (active) active.skip = true; };
  next.onclick = () => { const i = HIGHLIGHTS.findIndex(h => h.id === active?.id); start(HIGHLIGHTS[(i + 1) % HIGHLIGHTS.length].id); };
  done.onclick = finish;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (active) stop('Paused. Explore from here.'); else hidePanel(); } });
  // Touching the scene during a flight hands control straight back to the visitor.
  for (const type of ['pointerdown', 'wheel']) canvasHost.addEventListener(type, () => { if (active?.flying) stop('Paused. Explore from here.'); }, {passive: true});

  function showPanel() { panel.hidden = false; open.setAttribute('aria-expanded', 'true'); cards.querySelector('button')?.focus(); }
  function hidePanel() { panel.hidden = true; open.setAttribute('aria-expanded', 'false'); }

  // Enable the button once the dataset and color modes are ready; honour ?highlight=<id> links.
  (async () => {
    while (!ready()) await wait(250);
    open.disabled = false;
    const requested = new URLSearchParams(location.search).get('highlight');
    if (requested && findHighlight(requested)) start(requested);
  })();

  function ready() {
    const {manifest} = api.state();
    return !!manifest && !$('surveyColorMode')?.disabled;
  }

  // ------------------------------------------------------------ camera
  const vec = v => [v.x, v.y, v.z];
  function currentPose() { const {camera, controls} = api.state(); return {position: vec(camera.position), target: vec(controls.target)}; }
  function applyPose(p) {
    const {camera, controls} = api.state();
    camera.position.set(...p.position); controls.target.set(...p.target); controls.update();
  }
  // Where fit() would put the camera for these bounds, without leaving it there.
  function poseFor(bounds, view = 'perspective') {
    const {camera} = api.state(), before = currentPose(), near = camera.near, far = camera.far;
    api.fit(bounds, view);
    const pose = currentPose();
    applyPose(before); camera.near = near; camera.far = far; camera.updateProjectionMatrix();
    return pose;
  }
  function fly(to, seconds, token) {
    const from = currentPose(), {camera, controls} = api.state();
    const damping = controls.enableDamping; controls.enableDamping = false; controls.enabled = false;
    camera.near = Math.max(.5, Math.min(camera.near, 1)); camera.far = Math.max(camera.far, 1e7); camera.updateProjectionMatrix();
    active.flying = true;
    return new Promise(resolve => {
      const started = performance.now(), ms = seconds * 1000;
      const step = now => {
        const finished = token !== run || active?.skip || now - started >= ms;
        applyPose(finished ? (token === run ? to : currentPose()) : interpolatePose(from, to, easeInOut((now - started) / ms)));
        if (!finished) { requestAnimationFrame(step); return; }
        controls.enableDamping = damping; controls.enabled = true;
        if (active) active.flying = false;
        resolve(token === run);
      };
      requestAnimationFrame(step);
    });
  }

  // ------------------------------------------------------------ sequence
  async function start(id) {
    const h = findHighlight(id);
    if (!h || !ready()) return;
    const token = ++run;
    active = {id, skip: false, flying: false};
    hidePanel();
    caption.hidden = false; skip.hidden = false; next.hidden = true; done.hidden = true; tourLink.hidden = true;
    caption.dataset.highlight = id;
    const state = api.state();
    if (state.planActive) api.orientView('perspective');
    api.clearSelection();
    const counts = datasetCounts(state.manifest, api.surveyColors.operatorModel?.());
    const focus = h.focusWell != null ? state.manifest.wells.find(w => w.id === h.focusWell) : null;
    const shots = {
      establish: state.manifest.bounds,
      region: regionalBounds(h.region),
      focus: focus?.bounds || (h.focusWiden ? regionalBounds(h.region, h.focusWiden, 0) : h.region),
    };
    const instant = reducedMotion();
    for (let i = 0; i < h.stages.length; i++) {
      if (token !== run) return;
      const stage = h.stages[i];
      dots.forEach((d, j) => d.classList.toggle('on', j <= i));
      text.textContent = stage.caption(counts);
      setColor(stage.color);
      const view = stage.kind === 'focus' ? h.focusView || 'perspective' : 'perspective';
      const pose = poseFor(shots[stage.kind], view);
      if (instant) { applyPose(pose); if (!active.skip) await wait(TIMING.reducedMotionHold * 1000); }
      else if (!await fly(pose, TIMING[stage.kind], token)) return;
      if (token !== run) return;
      if (stage.kind === 'focus' && focus) api.select(focus);
      if (stage.kind === 'establish' && !instant && !active.skip) await wait(1200);
    }
    if (token !== run) return;
    // Land exactly where "Zoom to well" / "Fit" would, so controls behave normally afterwards.
    api.fit(shots.focus, h.focusView || 'perspective');
    text.textContent = h.note;
    skip.hidden = true; next.hidden = false; done.hidden = false;
    tourLink.hidden = !h.tourLink; if (h.tourLink) tourLink.href = h.tourLink;
    active.flying = false;
    done.focus({preventScroll: true});
  }

  function setColor(mode) {
    if (api.surveyColors.mode?.() === mode) return;
    if (mode === 'operator' && !api.surveyColors.operatorModel?.()) return;
    api.setWellContext('normal');
    api.surveyColors.setMode(mode);
  }

  function stop(message) {
    run++;
    if (!active) return;
    active = null;
    text.textContent = message;
    skip.hidden = true; next.hidden = false; done.hidden = false;
  }

  function finish() { run++; active = null; caption.hidden = true; open.focus({preventScroll: true}); }

  return {start, stop, highlights: HIGHLIGHTS};
}
