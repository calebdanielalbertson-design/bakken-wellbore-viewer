// Load the third-party player only after the visitor chooses to watch.
const play = document.getElementById('overview-play');
const player = document.getElementById('overview-player');

play?.addEventListener('click', () => {
  if (!player || player.querySelector('iframe')) return;
  const frame = document.createElement('iframe');
  frame.title = 'Bakken Subsurface Analytics — 75-second viewer overview';
  frame.src = 'https://www.youtube-nocookie.com/embed/Q2YHrcazXAg?autoplay=1&playsinline=1&rel=0';
  frame.width = '1920';
  frame.height = '1080';
  frame.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen; web-share';
  frame.allowFullscreen = true;
  frame.referrerPolicy = 'strict-origin-when-cross-origin';
  frame.tabIndex = 0;
  player.replaceChildren(frame);
  frame.focus();
}, {once: true});
