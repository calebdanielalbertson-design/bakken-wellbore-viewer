import {installPublicAssetFetch} from './public-assets.js';
try{await installPublicAssetFetch();await import('./app.js')}catch(error){document.getElementById('message').textContent='Could not load the public snapshot: '+error.message;}
