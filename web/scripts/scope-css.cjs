#!/usr/bin/env node
/* 把普通 CSS 文件整体加作用域前缀（供合并单 App 使用）：
   - :root / body → .{scope}
   - 其余选择器 → .{scope} {sel}
   - @media 内部递归；@keyframes 保持全局
   用法：node scripts/scope-css.cjs <in.css> <scope> <out.css> */
const fs = require('fs')
const [, , srcPath, scope, outPath] = process.argv
const css = fs.readFileSync(srcPath, 'utf8')

function prefixSelector(sel) {
  sel = sel.trim()
  if (!sel) return sel
  if (sel.startsWith('@')) return sel
  if (sel === '*') return '.' + scope + ' *'
  if (sel === ':root') return '.' + scope
  if (sel === 'html' || sel === 'body' || sel === 'html,body') return '.' + scope
  if (sel.startsWith('body')) return '.' + scope + sel.slice(4)
  return sel.split(',').map(s => '.' + scope + ' ' + s.trim()).join(', ')
}

function matchBrace(input, start) {
  let depth = 0
  for (let i = start; i < input.length; i++) {
    const ch = input[i]
    if (ch === '{') depth++
    else if (ch === '}') { depth--; if (depth === 0) return i }
  }
  return -1
}

function transform(input) {
  let out = ''
  let i = 0
  while (i < input.length) {
    const braceOpen = input.indexOf('{', i)
    if (braceOpen < 0) { out += input.slice(i); break }
    let selector = input.slice(i, braceOpen)
    if (selector.includes('/*')) {
      const cStart = i + selector.indexOf('/*')
      const cEnd = input.indexOf('*/', cStart)
      if (cEnd < 0) { out += input.slice(i); break }
      if (cEnd + 2 <= i) { out += input.slice(i, braceOpen); i = braceOpen; continue }
      out += input.slice(i, cEnd + 2)
      i = cEnd + 2
      continue
    }
    const braceClose = matchBrace(input, braceOpen)
    if (braceClose < 0) { out += input.slice(i); break }
    const body = input.slice(braceOpen + 1, braceClose)
    const trimmed = selector.trim()
    if (trimmed.startsWith('@keyframes') || trimmed.startsWith('@-webkit-keyframes')) {
      out += selector + '{' + body + '}'
    } else if (trimmed.startsWith('@media')) {
      out += selector + '{' + transform(body) + '}'
    } else {
      out += prefixSelector(selector) + '{' + body + '}'
    }
    i = braceClose + 1
  }
  return out
}

const result = transform(css)
fs.writeFileSync(outPath, result, 'utf8')
console.log('written', outPath, result.length, 'chars')
