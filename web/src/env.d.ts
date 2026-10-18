/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

// APK 原生桥（WebView addJavascriptInterface(bridge, "Native")）
// 方法声明为可选：旧版本 APK 可能只注入了部分方法，运行时需逐个判断
interface NativeBridge {
  loadPref?(key: string, def: string): string
  savePref?(key: string, value: string): void
  discoverServers?(): string
  pickBackground?(): void
  clearBackground?(): void
  getBackgroundUri?(): string
  saveBackgroundUri?(uri: string): void
  downloadImage?(url: string): void
  getAndroid?(): string
  // 网页热更新（files/www 优先于 assets/www）
  getWebVersion?(): number
  saveWebFile?(name: string, content: string): boolean
  setWebVersion?(version: number): void
  clearWebCache?(): void
  reloadApp?(): void
}
declare global {
  interface Window {
    Native?: NativeBridge
    ServerMod?: {
      IS_APP: boolean
      KEY: string
      getServer(): string
      setServer(v: string): string
      api(path: string, opts?: any): Promise<any>
      health(): Promise<boolean>
      discover(): { name?: string; ip: string; port?: number; url: string }[]
      autoConnect(): Promise<string | null>
    }
    QBANK_DATA?: {
      schema: number
      license: string
      generated_at: string
      generator: string
      intervals: number[]
      questions: any[]
      cards: any[]
    }
    QBankStatic?: {
      make(data: any, storage: Storage | null): QBankStore
    }
  }
}
export interface QBankStore {
  stats(): any
  pick(opts: any): any[]
  search(q: string, limit?: string | null): any[]
  banks(): any[]
  sections(): any[]
  cards(q?: string | null, chapter?: string | null, limit?: string | null): any[]
  chapters(): any[]
  wrong_list(): any[]
  import_progress(p: any): number
  export_progress(): any
  grade(id: string, given: any): any
  mark(id: string, result: string): any
  manual_checkin(): any
  checkin(month?: string | null): any
  note_save?(id: string, text: string, flag?: boolean): any
  note_delete?(id: string): any
  note_list?(): any[]
}
