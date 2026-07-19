#!/usr/bin/env node
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync(new URL('../my-portfolio_5.html',import.meta.url),'utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match=>match[1]);
if(scripts.length!==1) throw new Error(`expected one inline script, found ${scripts.length}`);
new vm.Script(scripts[0],{filename:'my-portfolio_5.inline.js'});

const ids=[...html.matchAll(/\sid="([^"]+)"/g)].map(match=>match[1]);
const duplicates=ids.filter((id,index)=>ids.indexOf(id)!==index);
if(duplicates.length) throw new Error(`duplicate ids: ${[...new Set(duplicates)].join(', ')}`);

const declarations=new Set([...scripts[0].matchAll(/(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/g)].map(match=>match[1]));
const handlers=[...html.matchAll(/\s(?:onclick|onchange)="\s*([A-Za-z_$][\w$]*)\s*\(/g)].map(match=>match[1]);
const missing=[...new Set(handlers.filter(name=>!declarations.has(name)))];
if(missing.length) throw new Error(`missing inline handlers: ${missing.join(', ')}`);

for(const forbidden of ['api.twelvedata.com','financialmodelingprep.com/stable/']){
  if(html.includes(forbidden)) throw new Error(`paid API call remains: ${forbidden}`);
}
for(const required of ['researchMetrics','researchFinancials','correlationMatrix','xrayResult','workspaceKey','planningResult']){
  if(!ids.includes(required)) throw new Error(`required UI element missing: ${required}`);
}
console.log(`app static validation OK: ${ids.length} unique ids / ${handlers.length} inline handlers`);
