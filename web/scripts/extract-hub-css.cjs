#!/usr/bin/env node
/* 把 hub.html 内联 CSS 抽取为 src/hub/hub.css：
   - body/html/:root 规则转成 .hub 作用域
   - 其余选择器统一加 .hub 前缀
   - @media 内部递归处理；@keyframes 保持全局（花括号配对扫描，避免把
     keyframes 内部的 to{...} 误当成选择器）
   用法：node scripts/extract-hub-css.cjs <hub.html 路径> <输出 css 路径> */
const fs = require('fs')
const [, , srcPath, outPath] = process.argv
const html = fs.readFileSync(srcPath, 'utf8')
const css = html.match(/<style>([\s\S]*?)<\/style>/)[1]

function prefixSelector(sel) {
  sel = sel.trim()
  if (!sel) return sel
  if (sel.startsWith('@')) return sel
  // 全局型规则：保持原名（* 号重置保持全局）
  if (sel === '*') return sel
  if (sel === ':root') return '.hub'
  if (sel === 'html,body') return '.hub'
  // body 单体 → .hub
  if (sel === 'body') return '.hub'
  if (sel.startsWith('body.has-bgimg')) return sel.replace(/^body/, '.hub')
  // [data-scene="x"] → .hub[data-scene="x"]
  if (sel.startsWith('[data-scene')) return '.hub' + sel
  // 已经是 #app 之类的直接加前缀
  return sel.split(',').map(s => '.hub ' + s.trim()).join(', ')
}

/* 从 start 起找与 input[start] == '{' 配对的 '}'，返回结束下标（含） */
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
  const n = input.length
  while (i < n) {
    const braceOpen = input.indexOf('{', i)
    if (braceOpen < 0) { out += input.slice(i); break }
    let selector = input.slice(i, braceOpen)
    // 跳过注释（整段注释可能跨行，先找 */ 再继续）
    if (selector.includes('/*')) {
      const cStart = i + selector.indexOf('/*')   // 绝对下标
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
      // 保持全局：内部 from/to/百分比选择器原样保留
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
