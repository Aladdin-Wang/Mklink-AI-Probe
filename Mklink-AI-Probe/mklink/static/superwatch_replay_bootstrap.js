import { mountReplayButton } from './superwatch_replay.js';
if (window.CONFIG?.mode === 'SuperWatch') {
  mountReplayButton(document.querySelector('.header-actions'), { language: window.CONFIG.lang });
}
