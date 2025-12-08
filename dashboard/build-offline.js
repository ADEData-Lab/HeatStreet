const fs = require('fs');
const path = require('path');

// Read the built files
const distPath = path.join(__dirname, 'dist');
const htmlPath = path.join(distPath, 'index.html');
const assetsPath = path.join(distPath, 'assets');

console.log('Building offline HTML version...');

// Read the HTML file
let html = fs.readFileSync(htmlPath, 'utf8');

// Find and inline CSS files
const cssFiles = fs.readdirSync(assetsPath).filter(f => f.endsWith('.css'));
cssFiles.forEach(cssFile => {
  const css = fs.readFileSync(path.join(assetsPath, cssFile), 'utf8');
  html = html.replace(
    new RegExp(`<link[^>]*href="[^"]*${cssFile}"[^>]*>`, 'g'),
    `<style>${css}</style>`
  );
});

// Find and inline JS files
const jsFiles = fs.readdirSync(assetsPath).filter(f => f.endsWith('.js'));
jsFiles.forEach(jsFile => {
  const js = fs.readFileSync(path.join(assetsPath, jsFile), 'utf8');
  html = html.replace(
    new RegExp(`<script[^>]*src="[^"]*${jsFile}"[^>]*>`, 'g'),
    `<script type="module">${js}`
  );
});

// Write offline version
const offlinePath = path.join(__dirname, 'heat-street-dashboard-offline.html');
fs.writeFileSync(offlinePath, html);

console.log(`✓ Offline HTML created: ${offlinePath}`);
console.log(`  File size: ${(fs.statSync(offlinePath).size / 1024).toFixed(2)} KB`);
