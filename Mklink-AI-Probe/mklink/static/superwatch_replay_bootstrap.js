import { mountReplayButton } from './superwatch_replay.js';
if (window.CONFIG?.mode === 'SuperWatch') {
  document.getElementById('btn-export-csv')?.remove();
  mountReplayButton(document.querySelector('.header-actions'), { language: window.CONFIG.lang });
}
