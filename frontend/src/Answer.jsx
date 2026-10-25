import React from 'react';

export default function Answer({text}) {
  const blocks = [], lines = text.split('\n');
  const inline = value => value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part,i)=>part.startsWith('**')?<strong key={i}>{part.slice(2,-2)}</strong>:part.startsWith('`')?<code key={i}>{part.slice(1,-1)}</code>:part);
  for(let i=0;i<lines.length;i++) {
    const line=lines[i];
    if(line.startsWith('```')) { const code=[]; while(++i<lines.length&&!lines[i].startsWith('```'))code.push(lines[i]); blocks.push(<pre key={i}>{code.join('\n')}</pre>); }
    else if(/^#{1,6}\s/.test(line)) { const level=Math.min(4,line.match(/^#+/)[0].length+1);blocks.push(React.createElement(`h${level}`,{key:i},inline(line.replace(/^#+\s/,'')))); }
    else if(/^\s*(?:[-*]|\d+\.)\s/.test(line)) { const items=[];const ordered=/^\s*\d+\./.test(line);while(i<lines.length&&/^\s*(?:[-*]|\d+\.)\s/.test(lines[i])){items.push(<li key={i}>{inline(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s/,''))}</li>);i++;}i--;blocks.push(React.createElement(ordered?'ol':'ul',{key:i},items)); }
    else if(line.trim()) blocks.push(<p key={i}>{inline(line)}</p>);
  }
  return <div className="answer formatted-answer">{blocks}</div>;
}
