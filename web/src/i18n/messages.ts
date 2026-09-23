export const LOCALES = ["zh-Hant", "zh-Hans", "en"] as const;
export type Locale = (typeof LOCALES)[number];

export const LOCALE_LABEL: Record<Locale, string> = {
  "zh-Hant": "繁體中文",
  "zh-Hans": "简体中文",
  en: "English",
};

export function intlTag(locale: Locale) {
  if (locale === "zh-Hans") return "zh-CN";
  if (locale === "en") return "en";
  return "zh-TW";
}

export type UiErrorKey = "qr" | "qrLogin" | "apiId" | "apiHash" | "phone" | "code" | "password";

export type Messages = {
  docTitle: string;
  skip: string;
  close: string;
  saving: string;
  search: string;
  edit: string;
  remove: string;
  add: string;
  listSep: string;
  estimatePrefix: string;
  lang: { button: string; menu: string };
  conn: {
    aria: string;
    stream: string;
    live: string;
    reconnecting: string;
    connecting: string;
    tgOn: string;
    tgOff: string;
    pauseLoading: string;
    start: string;
    pause: string;
  };
  stage: {
    aria: string;
    tasks: string;
    parallel: string;
    hits: string;
    misses: string;
    inbox: string;
    inboxTitle: string;
    loading: string;
    needKey: string;
    viewSettings: string;
    needTelegram: string;
    viewTelegram: string;
    shellAria: string;
    telegram: string;
    settings: string;
    tags: string;
    batchFail: string;
    recentBatch: (message: string) => string;
    queue: string;
    queueEmpty: string;
    unnamedTask: string;
    queued: (count: number) => string;
    parallelBadge: (busy: number, cap: number) => string;
    engineJev: string;
    engineLaya: string;
    modelTitle: string;
    adjustParallel: string;
    running: string;
    standby: string;
    idle: string;
    aiAria: (engine: string, status: string, busy: number, cap: number) => string;
    parallelMeter: string;
    batch: string;
    jobCount: (count: number) => string;
    results: string;
    filterAria: string;
    searchLabel: string;
    searchPlaceholder: string;
    filterTask: string;
    allTasks: string;
    filterCategory: string;
    allCategories: string;
    minNoul: string;
    emptyHits: string;
    loadingMore: string;
    hit: string;
    miss: string;
    noText: string;
    unknownSender: string;
    taskFallback: string;
    thisBatch: (hits: number | string, total: number | string) => string;
    workerStatus: Record<"idle" | "packing" | "judging" | "done" | "error", string>;
  };
  tasks: {
    title: string;
    loading: string;
    empty: string;
    enabled: string;
    disabled: string;
    switchOn: (name: string) => string;
    switchOff: (name: string) => string;
    perBatch: (batch: number) => string;
    pool: (total: number, analyzed: number) => string;
    calls: (count: number, tokens: string) => string;
    confirmDelete: string;
    editTitle: string;
    createTitle: string;
    name: string;
    prompt: string;
    promptPlaceholder: string;
    batchSize: string;
    threshold: string;
    priority: string;
    enable: string;
    bindChannels: string;
    selectedCount: (selected: number, total: number) => string;
    searchChannelsLabel: string;
    searchChannels: string;
    channelsAria: string;
    pickChannelsFirst: string;
    noChannelMatch: (query: string) => string;
    typeTags: string;
    goTags: string;
    searchTagsLabel: string;
    searchTags: string;
    tagsAria: string;
    noTagsYet: string;
    noTagMatch: (query: string) => string;
    tagHint: string;
    tagTitle: string;
    tagSelected: (selected: number, cap: number) => string;
    save: string;
    template: string;
    templateBlank: string;
  };
  tags: {
    confirmDelete: string;
    reserved: string;
    otherDesc: string;
    title: string;
    intro: string;
    introTitle: string;
    searchLabel: string;
    searchPlaceholder: string;
    loading: string;
    listAria: string;
    reservedMeta: string;
    reservedBadge: string;
    noMatch: (query: string) => string;
    editTitle: string;
    createTitle: string;
    name: string;
    namePlaceholder: string;
    key: string;
    keyHint: string;
    keyPlaceholder: string;
    description: string;
    descriptionPlaceholder: string;
    save: string;
  };
  telegram: {
    loading: string;
    connected: string;
    disconnected: string;
    subscribed: (count: number) => string;
    lastError: (message: string) => string;
    channels: (count: number) => string;
    disconnect: string;
    apiHashSaved: string;
    phone: string;
    sendCode: string;
    useQr: string;
    codeLabel: string;
    apiIdTitle: string;
    codeAria: string;
    verify: string;
    channelTitle: string;
    selectedOf: (selected: number, total: number) => string;
    showing: (count: number) => string;
    selectAll: string;
    clear: string;
    resync: string;
    searchChannels: string;
    searchChannelsPlaceholder: string;
    channelListAria: string;
    channelsEmpty: string;
    noDialogMatch: (query: string) => string;
    done: string;
    qrTitle: string;
    qrHelp: string;
    qrAlt: string;
    qrGenerating: string;
    qrExpires: (time: string) => string;
    qrWaiting: string;
    qrRetry: string;
    twoFaTitle: string;
    cloudPassword: string;
    twoFaHint: string;
    twoFaTitleAttr: string;
    twoFaAria: string;
    submitPassword: string;
    errors: Record<UiErrorKey, string>;
  };
  settings: {
    title: string;
    loading: string;
    saved: string;
    cleared: string;
    confirmClear: string;
    key: string;
    keyTitle: string;
    keySet: string;
    keyMissing: string;
    model: string;
    modelPin: string;
    backend: string;
    backendJev: string;
    backendLaya: string;
    layaHint: string;
    layaConcurrency: string;
    layaSpend: string;
    unsavedBackend: (name: string) => string;
    layaActive: string;
    savedLaya: string;
    concurrencyLegend: string;
    concurrencyHint: string;
    concurrencyTitle: string;
    rangeAria: string;
    numberAria: string;
    maxAge: string;
    maxAgeHint: string;
    maxAgeTitle: string;
    dataDir: string;
    calls: string;
    hits: string;
    misses: string;
    pricingTitle: string;
    pricingTitleAttr: string;
    pricingHint: string;
    inputRate: string;
    outputRate: string;
    lowThreshold: string;
    save: string;
    clearKey: string;
    billingTitle: string;
    billingIntro: string;
    billingIntroLaya: string;
    insufficient: string;
    lowBalance: (credits: number | string | null) => string;
    loadingUsage: string;
    emptyUsage: string;
    today: string;
    sevenDays: string;
    allTime: string;
    callsTok: (calls: number, tokens: string, kind: string) => string;
    creditsLeft: string;
    creditsMissing: string;
    creditsAt: string;
    ledger: string;
    loadingLedger: string;
    emptyLedger: string;
    emptyLedgerLaya: string;
    colTime: string;
    colResult: string;
    colModel: string;
    colInput: string;
    colOutput: string;
    colSpend: string;
    colBalance: string;
    success: string;
    failed: string;
    prev: string;
    next: string;
  };
  billing: {
    insufficient: string;
    view: string;
    low: (credits: number | string | null) => string;
    chipAria: string;
    engineJev: string;
    engineLaya: string;
    layaFree: string;
    pastJev: string;
    today: string;
    balance: string;
    balanceMissing: string;
    kindActual: string;
    kindMixed: string;
    kindEstimate: string;
  };
};

const zhHant: Messages = {
  docTitle: "JEV Telegram 過濾器",
  skip: "跳到主要內容",
  close: "關閉",
  saving: "儲存中…",
  search: "搜尋",
  edit: "編輯",
  remove: "刪除",
  add: "新增",
  listSep: "、",
  estimatePrefix: "估計 ",
  lang: { button: "語言", menu: "選擇語言" },
  conn: {
    aria: "連線狀態",
    stream: "串流",
    live: "即時",
    reconnecting: "重連",
    connecting: "連線中",
    tgOn: "已連",
    tgOff: "未連",
    pauseLoading: "分析狀態載入中",
    start: "啟動分析",
    pause: "暫停分析",
  },
  stage: {
    aria: "舞台狀態",
    tasks: "任務",
    parallel: "並行",
    hits: "命中",
    misses: "未命中",
    inbox: "收訊",
    inboxTitle: "前面是資料庫已存訊息總數，括號是這次開頁後新收到的筆數。重新整理不會刪除訊息。",
    loading: "載入中…",
    needKey: "尚未設定 TypeSafe API Key，Jev 會保持閒置。",
    viewSettings: "查看設定",
    needTelegram: "Telegram 尚未連線。登入並勾選頻道後才會收訊。",
    viewTelegram: "查看 Telegram",
    shellAria: "Telegram、設定、標籤",
    telegram: "Telegram",
    settings: "設定",
    tags: "標籤",
    batchFail: "批次分析失敗",
    recentBatch: (message) => `最近批次錯誤：${message}`,
    queue: "佇列",
    queueEmpty: "訊息湊滿批次後會在此排隊。",
    unnamedTask: "未命名任務",
    queued: (count) => `${count} 條 · 排隊中`,
    parallelBadge: (busy, cap) => `並行 ${busy}/${cap}`,
    engineJev: "Jev",
    engineLaya: "Laya",
    modelTitle: "Jev 模型",
    adjustParallel: "調整並行數",
    running: "運轉中",
    standby: "待機",
    idle: "閒置",
    aiAria: (engine, status, busy, cap) => `${engine} ${status}，並行 ${busy}/${cap}`,
    parallelMeter: "並行",
    batch: "批次",
    jobCount: (count) => ` · ${count} 條`,
    results: "命中結果",
    filterAria: "篩選命中結果",
    searchLabel: "搜尋訊息文字、傳送者或頻道",
    searchPlaceholder: "搜尋文字、傳送者、頻道",
    filterTask: "依任務篩選",
    allTasks: "全部任務",
    filterCategory: "依類型篩選",
    allCategories: "全部類型",
    minNoul: "最低 noul",
    emptyHits: "尚無命中訊息。未達門檻的內容不會出現在這裡。",
    loadingMore: "正在載入較早的命中…",
    hit: "命中",
    miss: "未命中",
    noText: "（無文字）",
    unknownSender: "未知傳送者",
    taskFallback: "任務",
    thisBatch: (hits, total) => `本批 ${hits}/${total}`,
    workerStatus: { idle: "閒置", packing: "打包中", judging: "判斷中", done: "完成", error: "重試中" },
  },
  tasks: {
    title: "任務",
    loading: "載入任務…",
    empty: "還沒有任務。新增後 Worker 會依批次大小領取訊息。",
    enabled: "啟用",
    disabled: "停用",
    switchOn: (name) => `啟用任務「${name}」`,
    switchOff: (name) => `停用任務「${name}」`,
    perBatch: (batch) => `${batch} 條/批`,
    pool: (total, analyzed) => `${total} 則 · 已分析 ${analyzed}`,
    calls: (count, tokens) => `${count} 次 · ${tokens} tok`,
    confirmDelete: "確定刪除此任務？",
    editTitle: "編輯任務",
    createTitle: "新增任務",
    name: "名稱",
    prompt: "任務 Prompt",
    promptPlaceholder: "描述要過濾的條件，例如：找出與台股或 AI 晶片相關的討論",
    batchSize: "批次大小",
    threshold: "命中門檻",
    priority: "優先級",
    enable: "啟用此任務",
    bindChannels: "綁定已訂閱頻道",
    selectedCount: (selected, total) => `${selected} 已選 · ${total} 個`,
    searchChannelsLabel: "搜尋已訂閱頻道",
    searchChannels: "搜尋頻道",
    channelsAria: "綁定已訂閱頻道",
    pickChannelsFirst: "請先在 Telegram 勾選頻道。",
    noChannelMatch: (query) => `沒有符合「${query}」的頻道。`,
    typeTags: "類型標籤",
    goTags: "到標籤區",
    searchTagsLabel: "搜尋類型標籤",
    searchTags: "搜尋標籤",
    tagsAria: "類型標籤",
    noTagsYet: "尚未建立標籤。",
    noTagMatch: (query) => `沒有符合「${query}」的標籤。`,
    tagHint: "可複選，自動加上 other。",
    tagTitle: "未選任何標籤時不送 choice 題，只問是否相關。",
    tagSelected: (selected, cap) => `已選 ${selected} / ${cap}`,
    save: "儲存任務",
    template: "範本",
    templateBlank: "空白",
  },
  tags: {
    confirmDelete: "確定刪除此標籤？已選用的任務會失去此選項。",
    reserved: "系統保留",
    otherDesc: "不符合以上任一類型",
    title: "標籤",
    intro: "呼叫時自動加上 other。",
    introTitle: "任務只選用這些標籤。呼叫時會自動加上保留的 other。",
    searchLabel: "搜尋標籤",
    searchPlaceholder: "搜尋標籤",
    loading: "載入標籤…",
    listAria: "標籤列表",
    reservedMeta: "系統保留 · 不符合以上任一類型",
    reservedBadge: "保留",
    noMatch: (query) => `沒有符合「${query}」的標籤。`,
    editTitle: "編輯標籤",
    createTitle: "新增標籤",
    name: "名稱",
    namePlaceholder: "例如 股票",
    key: "Key / id",
    keyHint: "留空則自動產生；不可為 other。",
    keyPlaceholder: "stock",
    description: "說明（Jev 判斷準則）",
    descriptionPlaceholder: "這種類型何時成立，例如：討論個股、指數或盤勢",
    save: "儲存標籤",
  },
  telegram: {
    loading: "載入中…",
    connected: "已連線",
    disconnected: "未連線",
    subscribed: (count) => `已訂閱 ${count}`,
    lastError: (message) => `上次錯誤：${message}`,
    channels: (count) => `頻道 ${count}`,
    disconnect: "中斷",
    apiHashSaved: "已儲存，留空沿用",
    phone: "手機號碼（含國碼）",
    sendCode: "寄送驗證碼",
    useQr: "QR 登入",
    codeLabel: "驗證碼",
    apiIdTitle: "用戶帳號登入，非 Bot。api_id／api_hash 取自 my.telegram.org。",
    codeAria: "Telegram 驗證碼",
    verify: "驗證",
    channelTitle: "頻道勾選",
    selectedOf: (selected, total) => `已選 ${selected} / ${total}`,
    showing: (count) => `顯示 ${count}`,
    selectAll: "全選",
    clear: "清空",
    resync: "重新同步",
    searchChannels: "搜尋頻道",
    searchChannelsPlaceholder: "名稱或 ID",
    channelListAria: "頻道列表",
    channelsEmpty: "登入後才會列出已加入的群組／頻道。",
    noDialogMatch: (query) => `沒有符合「${query}」的對話。`,
    done: "完成",
    qrTitle: "掃描 QR 碼",
    qrHelp: "設定 → 裝置 → 連結桌面裝置",
    qrAlt: "Telegram 登入 QR code",
    qrGenerating: "產生 QR 中…",
    qrExpires: (time) => `到期 ${time}`,
    qrWaiting: "等待手機確認…",
    qrRetry: "重新產生",
    twoFaTitle: "兩步驟驗證",
    cloudPassword: "雲端密碼",
    twoFaHint: "Telegram 已確認這次登入。",
    twoFaTitleAttr: "請輸入兩步驟驗證的雲端密碼。",
    twoFaAria: "兩步驟驗證密碼",
    submitPassword: "送出密碼",
    errors: {
      qr: "無法產生 QR 碼，請重試。",
      qrLogin: "QR 登入失敗，請再試一次。",
      apiId: "請填寫有效的 api_id",
      apiHash: "請填寫 api_hash",
      phone: "請填寫手機號碼（含國碼）",
      code: "請輸入 Telegram 驗證碼",
      password: "請輸入兩步驟驗證密碼",
    },
  },
  settings: {
    title: "設定與計費",
    loading: "載入設定…",
    saved: "已儲存。並行數會立即套用。",
    cleared: "已清除 API Key。",
    confirmClear: "確定清除本機儲存的 TypeSafe API Key？",
    key: "TypeSafe API Key",
    keyTitle: "以 Fernet 加密寫入本機 SQLite，不會下發到瀏覽器。",
    keySet: "已設定，輸入新值可覆蓋",
    keyMissing: "尚未設定",
    model: "Jev 模型",
    modelPin: "jev-1.13.0（建議 pin）",
    backend: "分析後端",
    backendJev: "Jev",
    backendLaya: "Laya",
    layaHint: "本機多語模型。自訂決策未微調時接近亂猜。",
    layaConcurrency: "同時幾批，模型本身只載一份、推論逐筆。",
    layaSpend: "本機 · 無費用",
    unsavedBackend: (name) => `尚未儲存。目前分析仍是 ${name}。`,
    layaActive: "目前分析是 Laya。本機 · 無費用。",
    savedLaya: "已儲存。分析改走 Laya。",
    concurrencyLegend: "並行",
    concurrencyHint: "同時幾路 API。",
    concurrencyTitle: "同時判斷的 asyncio 協程數，不是系統執行緒。舞台忙碌時以並行 n/m 表示。",
    rangeAria: "並行數滑桿",
    numberAria: "並行數",
    maxAge: "只分析最近幾天",
    maxAgeHint: "0 表示不限。",
    maxAgeTitle: "正整數只分析最近 N 天內、該任務尚未分析的訊息，不會刪除較舊訊息。",
    dataDir: "資料目錄（唯讀）",
    calls: "呼叫",
    hits: "命中",
    misses: "未命中",
    pricingTitle: "估計單價",
    pricingTitleAttr: "官方 Usage 沒有 cost。未回傳成本時金額標為估計，預設輸入約 $0.42／百萬 token。",
    pricingHint: "未回傳成本時標為估計。",
    inputRate: "輸入 USD / 百萬 tok",
    outputRate: "輸出 USD / 百萬 tok",
    lowThreshold: "低餘額門檻",
    save: "儲存設定",
    clearKey: "清除 API Key",
    billingTitle: "用量",
    billingIntro: "每次呼叫一筆；餘額僅在 API 回傳時顯示。",
    billingIntroLaya: "本機 · 無費用。",
    insufficient: "TypeSafe 額度不足（HTTP 402）。",
    lowBalance: (credits) => `餘額已低於門檻${credits == null ? "" : `（剩餘 ${credits}）`}。`,
    loadingUsage: "載入用量…",
    emptyUsage: "尚無用量。",
    today: "今日",
    sevenDays: "近 7 日",
    allTime: "累計",
    callsTok: (calls, tokens, kind) => `${calls} 次 · ${tokens} tok${kind ? ` · ${kind}` : ""}`,
    creditsLeft: "剩餘額度",
    creditsMissing: "API 未回傳",
    creditsAt: "最近餘額",
    ledger: "呼叫帳本",
    loadingLedger: "載入帳本…",
    emptyLedger: "帳本是空的。",
    emptyLedgerLaya: "尚無 Laya 呼叫。",
    colTime: "時間",
    colResult: "結果",
    colModel: "模型",
    colInput: "輸入",
    colOutput: "輸出",
    colSpend: "花費",
    colBalance: "餘額",
    success: "成功",
    failed: "失敗",
    prev: "上一頁",
    next: "下一頁",
  },
  billing: {
    insufficient: "TypeSafe 額度不足（HTTP 402）。請儲值後再繼續分析。",
    view: "查看計費",
    low: (credits) => `TypeSafe 餘額偏低${credits != null ? `（剩餘 ${credits}）` : ""}。`,
    chipAria: "用量與計費",
    engineJev: "Jev",
    engineLaya: "Laya",
    layaFree: "本機 · 無費用",
    pastJev: "過去 Jev",
    today: "今日",
    balance: "餘額",
    balanceMissing: "未回傳",
    kindActual: "官方",
    kindMixed: "混合",
    kindEstimate: "估計",
  },
};

const zhHans: Messages = {
  docTitle: "JEV Telegram 过滤器",
  skip: "跳到主要内容",
  close: "关闭",
  saving: "保存中…",
  search: "搜索",
  edit: "编辑",
  remove: "删除",
  add: "新增",
  listSep: "、",
  estimatePrefix: "估计 ",
  lang: { button: "语言", menu: "选择语言" },
  conn: {
    aria: "连接状态",
    stream: "串流",
    live: "实时",
    reconnecting: "重连",
    connecting: "连接中",
    tgOn: "已连",
    tgOff: "未连",
    pauseLoading: "分析状态加载中",
    start: "启动分析",
    pause: "暂停分析",
  },
  stage: {
    aria: "舞台状态",
    tasks: "任务",
    parallel: "并行",
    hits: "命中",
    misses: "未命中",
    inbox: "收讯",
    inboxTitle: "前面是数据库已存消息总数，括号是这次打开页面后新收到的条数。刷新不会删除消息。",
    loading: "加载中…",
    needKey: "尚未设置 TypeSafe API Key，Jev 会保持闲置。",
    viewSettings: "查看设置",
    needTelegram: "Telegram 尚未连接。登录并勾选频道后才会收讯。",
    viewTelegram: "查看 Telegram",
    shellAria: "Telegram、设置、标签",
    telegram: "Telegram",
    settings: "设置",
    tags: "标签",
    batchFail: "批次分析失败",
    recentBatch: (message) => `最近批次错误：${message}`,
    queue: "队列",
    queueEmpty: "消息凑满批次后会在此排队。",
    unnamedTask: "未命名任务",
    queued: (count) => `${count} 条 · 排队中`,
    parallelBadge: (busy, cap) => `并行 ${busy}/${cap}`,
    engineJev: "Jev",
    engineLaya: "Laya",
    modelTitle: "Jev 模型",
    adjustParallel: "调整并行数",
    running: "运转中",
    standby: "待机",
    idle: "闲置",
    aiAria: (engine, status, busy, cap) => `${engine} ${status}，并行 ${busy}/${cap}`,
    parallelMeter: "并行",
    batch: "批次",
    jobCount: (count) => ` · ${count} 条`,
    results: "命中结果",
    filterAria: "筛选命中结果",
    searchLabel: "搜索消息文字、发送者或频道",
    searchPlaceholder: "搜索文字、发送者、频道",
    filterTask: "按任务筛选",
    allTasks: "全部任务",
    filterCategory: "按类型筛选",
    allCategories: "全部类型",
    minNoul: "最低 noul",
    emptyHits: "尚无命中消息。未达门槛的内容不会出现在这里。",
    loadingMore: "正在加载较早的命中…",
    hit: "命中",
    miss: "未命中",
    noText: "（无文字）",
    unknownSender: "未知发送者",
    taskFallback: "任务",
    thisBatch: (hits, total) => `本批 ${hits}/${total}`,
    workerStatus: { idle: "闲置", packing: "打包中", judging: "判断中", done: "完成", error: "重试中" },
  },
  tasks: {
    title: "任务",
    loading: "加载任务…",
    empty: "还没有任务。新增后 Worker 会按批次大小领取消息。",
    enabled: "启用",
    disabled: "停用",
    switchOn: (name) => `启用任务「${name}」`,
    switchOff: (name) => `停用任务「${name}」`,
    perBatch: (batch) => `${batch} 条/批`,
    pool: (total, analyzed) => `${total} 则 · 已分析 ${analyzed}`,
    calls: (count, tokens) => `${count} 次 · ${tokens} tok`,
    confirmDelete: "确定删除此任务？",
    editTitle: "编辑任务",
    createTitle: "新增任务",
    name: "名称",
    prompt: "任务 Prompt",
    promptPlaceholder: "描述要过滤的条件，例如：找出与台股或 AI 芯片相关的讨论",
    batchSize: "批次大小",
    threshold: "命中门槛",
    priority: "优先级",
    enable: "启用此任务",
    bindChannels: "绑定已订阅频道",
    selectedCount: (selected, total) => `${selected} 已选 · ${total} 个`,
    searchChannelsLabel: "搜索已订阅频道",
    searchChannels: "搜索频道",
    channelsAria: "绑定已订阅频道",
    pickChannelsFirst: "请先在 Telegram 勾选频道。",
    noChannelMatch: (query) => `没有符合「${query}」的频道。`,
    typeTags: "类型标签",
    goTags: "到标签区",
    searchTagsLabel: "搜索类型标签",
    searchTags: "搜索标签",
    tagsAria: "类型标签",
    noTagsYet: "尚未建立标签。",
    noTagMatch: (query) => `没有符合「${query}」的标签。`,
    tagHint: "可多选，自动加上 other。",
    tagTitle: "未选任何标签时不送 choice 题，只问是否相关。",
    tagSelected: (selected, cap) => `已选 ${selected} / ${cap}`,
    save: "保存任务",
    template: "范本",
    templateBlank: "空白",
  },
  tags: {
    confirmDelete: "确定删除此标签？已选用的任务会失去此选项。",
    reserved: "系统保留",
    otherDesc: "不符合以上任一类型",
    title: "标签",
    intro: "调用时自动加上 other。",
    introTitle: "任务只选用这些标签。调用时会自动加上保留的 other。",
    searchLabel: "搜索标签",
    searchPlaceholder: "搜索标签",
    loading: "加载标签…",
    listAria: "标签列表",
    reservedMeta: "系统保留 · 不符合以上任一类型",
    reservedBadge: "保留",
    noMatch: (query) => `没有符合「${query}」的标签。`,
    editTitle: "编辑标签",
    createTitle: "新增标签",
    name: "名称",
    namePlaceholder: "例如 股票",
    key: "Key / id",
    keyHint: "留空则自动生成；不可为 other。",
    keyPlaceholder: "stock",
    description: "说明（Jev 判断准则）",
    descriptionPlaceholder: "这种类型何时成立，例如：讨论个股、指数或盘势",
    save: "保存标签",
  },
  telegram: {
    loading: "加载中…",
    connected: "已连接",
    disconnected: "未连接",
    subscribed: (count) => `已订阅 ${count}`,
    lastError: (message) => `上次错误：${message}`,
    channels: (count) => `频道 ${count}`,
    disconnect: "断开",
    apiHashSaved: "已保存，留空沿用",
    phone: "手机号码（含国码）",
    sendCode: "发送验证码",
    useQr: "QR 登录",
    codeLabel: "验证码",
    apiIdTitle: "用户账号登录，非 Bot。api_id／api_hash 取自 my.telegram.org。",
    codeAria: "Telegram 验证码",
    verify: "验证",
    channelTitle: "频道勾选",
    selectedOf: (selected, total) => `已选 ${selected} / ${total}`,
    showing: (count) => `显示 ${count}`,
    selectAll: "全选",
    clear: "清空",
    resync: "重新同步",
    searchChannels: "搜索频道",
    searchChannelsPlaceholder: "名称或 ID",
    channelListAria: "频道列表",
    channelsEmpty: "登录后才会列出已加入的群组／频道。",
    noDialogMatch: (query) => `没有符合「${query}」的对话。`,
    done: "完成",
    qrTitle: "扫描 QR 码",
    qrHelp: "设置 → 设备 → 链接桌面设备",
    qrAlt: "Telegram 登录 QR code",
    qrGenerating: "生成 QR 中…",
    qrExpires: (time) => `到期 ${time}`,
    qrWaiting: "等待手机确认…",
    qrRetry: "重新生成",
    twoFaTitle: "两步验证",
    cloudPassword: "云端密码",
    twoFaHint: "Telegram 已确认这次登录。",
    twoFaTitleAttr: "请输入两步验证的云端密码。",
    twoFaAria: "两步验证密码",
    submitPassword: "提交密码",
    errors: {
      qr: "无法生成 QR 码，请重试。",
      qrLogin: "QR 登录失败，请再试一次。",
      apiId: "请填写有效的 api_id",
      apiHash: "请填写 api_hash",
      phone: "请填写手机号码（含国码）",
      code: "请输入 Telegram 验证码",
      password: "请输入两步验证密码",
    },
  },
  settings: {
    title: "设置与计费",
    loading: "加载设置…",
    saved: "已保存。并行数会立即套用。",
    cleared: "已清除 API Key。",
    confirmClear: "确定清除本机保存的 TypeSafe API Key？",
    key: "TypeSafe API Key",
    keyTitle: "以 Fernet 加密写入本机 SQLite，不会下发到浏览器。",
    keySet: "已设置，输入新值可覆盖",
    keyMissing: "尚未设置",
    model: "Jev 模型",
    modelPin: "jev-1.13.0（建议 pin）",
    backend: "分析后端",
    backendJev: "Jev",
    backendLaya: "Laya",
    layaHint: "本地多语模型。自定义决策未微调时接近乱猜。",
    layaConcurrency: "同时几批，模型本身只载一份、推理逐笔。",
    layaSpend: "本机 · 无费用",
    unsavedBackend: (name) => `尚未保存。当前分析仍是 ${name}。`,
    layaActive: "当前分析是 Laya。本机 · 无费用。",
    savedLaya: "已保存。分析改走 Laya。",
    concurrencyLegend: "并行",
    concurrencyHint: "同时几路 API。",
    concurrencyTitle: "同时判断的 asyncio 协程数，不是系统线程。舞台忙碌时以并行 n/m 表示。",
    rangeAria: "并行数滑杆",
    numberAria: "并行数",
    maxAge: "只分析最近几天",
    maxAgeHint: "0 表示不限。",
    maxAgeTitle: "正整数只分析最近 N 天内、该任务尚未分析的消息，不会删除较旧消息。",
    dataDir: "数据目录（只读）",
    calls: "调用",
    hits: "命中",
    misses: "未命中",
    pricingTitle: "估计单价",
    pricingTitleAttr: "官方 Usage 没有 cost。未回传成本时金额标为估计，默认输入约 $0.42／百万 token。",
    pricingHint: "未回传成本时标为估计。",
    inputRate: "输入 USD / 百万 tok",
    outputRate: "输出 USD / 百万 tok",
    lowThreshold: "低余额门槛",
    save: "保存设置",
    clearKey: "清除 API Key",
    billingTitle: "用量",
    billingIntro: "每次调用一笔；余额仅在 API 回传时显示。",
    billingIntroLaya: "本机 · 无费用。",
    insufficient: "TypeSafe 额度不足（HTTP 402）。",
    lowBalance: (credits) => `余额已低于门槛${credits == null ? "" : `（剩余 ${credits}）`}。`,
    loadingUsage: "加载用量…",
    emptyUsage: "尚无用量。",
    today: "今日",
    sevenDays: "近 7 日",
    allTime: "累计",
    callsTok: (calls, tokens, kind) => `${calls} 次 · ${tokens} tok${kind ? ` · ${kind}` : ""}`,
    creditsLeft: "剩余额度",
    creditsMissing: "API 未回传",
    creditsAt: "最近余额",
    ledger: "调用账本",
    loadingLedger: "加载账本…",
    emptyLedger: "账本是空的。",
    emptyLedgerLaya: "尚无 Laya 调用。",
    colTime: "时间",
    colResult: "结果",
    colModel: "模型",
    colInput: "输入",
    colOutput: "输出",
    colSpend: "花费",
    colBalance: "余额",
    success: "成功",
    failed: "失败",
    prev: "上一页",
    next: "下一页",
  },
  billing: {
    insufficient: "TypeSafe 额度不足（HTTP 402）。请储值后再继续分析。",
    view: "查看计费",
    low: (credits) => `TypeSafe 余额偏低${credits != null ? `（剩余 ${credits}）` : ""}。`,
    chipAria: "用量与计费",
    engineJev: "Jev",
    engineLaya: "Laya",
    layaFree: "本机 · 无费用",
    pastJev: "过去 Jev",
    today: "今日",
    balance: "余额",
    balanceMissing: "未回传",
    kindActual: "官方",
    kindMixed: "混合",
    kindEstimate: "估计",
  },
};

const en: Messages = {
  docTitle: "JEV Telegram Filter",
  skip: "Skip to main content",
  close: "Close",
  saving: "Saving…",
  search: "Search",
  edit: "Edit",
  remove: "Delete",
  add: "Add",
  listSep: ", ",
  estimatePrefix: "est. ",
  lang: { button: "Language", menu: "Choose language" },
  conn: {
    aria: "Connection status",
    stream: "Stream",
    live: "Live",
    reconnecting: "Reconnecting",
    connecting: "Connecting",
    tgOn: "On",
    tgOff: "Off",
    pauseLoading: "Loading analysis state",
    start: "Start analysis",
    pause: "Pause analysis",
  },
  stage: {
    aria: "Stage status",
    tasks: "Tasks",
    parallel: "Parallel",
    hits: "Hits",
    misses: "Misses",
    inbox: "Inbox",
    inboxTitle: "The number is stored messages. The count in parentheses is new since this page opened. Refresh does not delete messages.",
    loading: "Loading…",
    needKey: "TypeSafe API key is not set. Jev stays idle.",
    viewSettings: "View settings",
    needTelegram: "Telegram is not connected. Sign in and select channels to receive messages.",
    viewTelegram: "View Telegram",
    shellAria: "Telegram, settings, tags",
    telegram: "Telegram",
    settings: "Settings",
    tags: "Tags",
    batchFail: "Batch analysis failed",
    recentBatch: (message) => `Latest batch error: ${message}`,
    queue: "Queue",
    queueEmpty: "Messages line up here once a batch fills.",
    unnamedTask: "Untitled task",
    queued: (count) => `${count} msgs · queued`,
    parallelBadge: (busy, cap) => `Parallel ${busy}/${cap}`,
    engineJev: "Jev",
    engineLaya: "Laya",
    modelTitle: "Jev model",
    adjustParallel: "Adjust concurrency",
    running: "Running",
    standby: "Idle",
    idle: "Idle",
    aiAria: (engine, status, busy, cap) => `${engine} ${status}, parallel ${busy}/${cap}`,
    parallelMeter: "Parallel",
    batch: "Batch",
    jobCount: (count) => ` · ${count} msgs`,
    results: "Hits",
    filterAria: "Filter hit results",
    searchLabel: "Search message text, sender, or channel",
    searchPlaceholder: "Text, sender, channel",
    filterTask: "Filter by task",
    allTasks: "All tasks",
    filterCategory: "Filter by type",
    allCategories: "All types",
    minNoul: "Minimum noul",
    emptyHits: "No hits yet. Messages under the threshold do not appear here.",
    loadingMore: "Loading earlier hits…",
    hit: "Hit",
    miss: "Miss",
    noText: "(no text)",
    unknownSender: "Unknown sender",
    taskFallback: "Task",
    thisBatch: (hits, total) => `Batch ${hits}/${total}`,
    workerStatus: { idle: "Idle", packing: "Packing", judging: "Judging", done: "Done", error: "Retrying" },
  },
  tasks: {
    title: "Tasks",
    loading: "Loading tasks…",
    empty: "No tasks yet. After you add one, workers take messages by batch size.",
    enabled: "On",
    disabled: "Off",
    switchOn: (name) => `Enable task “${name}”`,
    switchOff: (name) => `Disable task “${name}”`,
    perBatch: (batch) => `${batch}/batch`,
    pool: (total, analyzed) => `${total} msgs · ${analyzed} analyzed`,
    calls: (count, tokens) => `${count} calls · ${tokens} tok`,
    confirmDelete: "Delete this task?",
    editTitle: "Edit task",
    createTitle: "New task",
    name: "Name",
    prompt: "Task prompt",
    promptPlaceholder: "Describe what to keep, for example: discussions about Taiwan stocks or AI chips",
    batchSize: "Batch size",
    threshold: "Hit threshold",
    priority: "Priority",
    enable: "Enable this task",
    bindChannels: "Subscribed channels",
    selectedCount: (selected, total) => `${selected} selected · ${total}`,
    searchChannelsLabel: "Search subscribed channels",
    searchChannels: "Search channels",
    channelsAria: "Subscribed channels",
    pickChannelsFirst: "Select channels in Telegram first.",
    noChannelMatch: (query) => `No channels match “${query}”.`,
    typeTags: "Type tags",
    goTags: "Open tags",
    searchTagsLabel: "Search type tags",
    searchTags: "Search tags",
    tagsAria: "Type tags",
    noTagsYet: "No tags yet.",
    noTagMatch: (query) => `No tags match “${query}”.`,
    tagHint: "Multiple allowed. other is added automatically.",
    tagTitle: "With none selected, the choice question is omitted and Jev only asks about relevance.",
    tagSelected: (selected, cap) => `${selected} / ${cap} selected`,
    save: "Save task",
    template: "Template",
    templateBlank: "Blank",
  },
  tags: {
    confirmDelete: "Delete this tag? Tasks using it will lose this option.",
    reserved: "Reserved",
    otherDesc: "None of the types above",
    title: "Tags",
    intro: "other is added automatically.",
    introTitle: "Tasks only use these tags. Calls automatically include the reserved other.",
    searchLabel: "Search tags",
    searchPlaceholder: "Search tags",
    loading: "Loading tags…",
    listAria: "Tag list",
    reservedMeta: "Reserved · none of the types above",
    reservedBadge: "Reserved",
    noMatch: (query) => `No tags match “${query}”.`,
    editTitle: "Edit tag",
    createTitle: "New tag",
    name: "Name",
    namePlaceholder: "e.g. Stocks",
    key: "Key / id",
    keyHint: "Leave blank to generate; cannot be other.",
    keyPlaceholder: "stock",
    description: "Description (how Jev decides)",
    descriptionPlaceholder: "When this type applies, for example: individual stocks, indexes, or market moves",
    save: "Save tag",
  },
  telegram: {
    loading: "Loading…",
    connected: "Connected",
    disconnected: "Disconnected",
    subscribed: (count) => `${count} subscribed`,
    lastError: (message) => `Last error: ${message}`,
    channels: (count) => `Channels ${count}`,
    disconnect: "Disconnect",
    apiHashSaved: "Saved; leave blank to keep",
    phone: "Phone (with country code)",
    sendCode: "Send code",
    useQr: "QR login",
    codeLabel: "Code",
    apiIdTitle: "User-account login, not a bot. api_id / api_hash come from my.telegram.org.",
    codeAria: "Telegram code",
    verify: "Verify",
    channelTitle: "Select channels",
    selectedOf: (selected, total) => `${selected} / ${total} selected`,
    showing: (count) => `Showing ${count}`,
    selectAll: "Select all",
    clear: "Clear",
    resync: "Sync again",
    searchChannels: "Search channels",
    searchChannelsPlaceholder: "Name or ID",
    channelListAria: "Channel list",
    channelsEmpty: "Joined groups and channels appear after you sign in.",
    noDialogMatch: (query) => `No chats match “${query}”.`,
    done: "Done",
    qrTitle: "Scan QR code",
    qrHelp: "Settings → Devices → Link Desktop Device",
    qrAlt: "Telegram login QR code",
    qrGenerating: "Creating QR…",
    qrExpires: (time) => `Expires ${time}`,
    qrWaiting: "Waiting for the phone…",
    qrRetry: "Create again",
    twoFaTitle: "Two-step verification",
    cloudPassword: "Cloud password",
    twoFaHint: "Telegram confirmed this login.",
    twoFaTitleAttr: "Enter the two-step verification cloud password.",
    twoFaAria: "Two-step verification password",
    submitPassword: "Submit password",
    errors: {
      qr: "Could not create a QR code. Try again.",
      qrLogin: "QR sign-in failed. Try again.",
      apiId: "Enter a valid api_id",
      apiHash: "Enter api_hash",
      phone: "Enter a phone number with country code",
      code: "Enter the Telegram code",
      password: "Enter the two-step verification password",
    },
  },
  settings: {
    title: "Settings and billing",
    loading: "Loading settings…",
    saved: "Saved. Concurrency applies immediately.",
    cleared: "API key cleared.",
    confirmClear: "Clear the TypeSafe API key stored on this machine?",
    key: "TypeSafe API Key",
    keyTitle: "Fernet-encrypted in local SQLite. Never sent to the browser.",
    keySet: "Set; type a new value to replace",
    keyMissing: "Not set",
    model: "Jev model",
    modelPin: "jev-1.13.0 (pinned)",
    backend: "Analysis backend",
    backendJev: "Jev",
    backendLaya: "Laya",
    layaHint: "Local multilingual model. Untuned custom decisions stay near chance.",
    layaConcurrency: "How many batches at once. One model copy; inferences run one by one.",
    layaSpend: "local · no charge",
    unsavedBackend: (name) => `Not saved yet. Analysis is still ${name}.`,
    layaActive: "Analysis is Laya. Local, no charge.",
    savedLaya: "Saved. Analysis now uses Laya.",
    concurrencyLegend: "Concurrency",
    concurrencyHint: "How many API calls at once.",
    concurrencyTitle: "How many asyncio coroutines judge at once. Not OS threads. The stage shows parallel n/m when busy.",
    rangeAria: "Concurrency slider",
    numberAria: "Concurrency",
    maxAge: "Only analyze recent days",
    maxAgeHint: "0 means no limit.",
    maxAgeTitle: "A positive integer analyzes only messages from the last N days that this task has not analyzed. Older messages are not deleted.",
    dataDir: "Data directory (read-only)",
    calls: "Calls",
    hits: "Hits",
    misses: "Misses",
    pricingTitle: "Estimated price",
    pricingTitleAttr: "Official Usage has no cost. When cost is omitted, amounts are marked estimated. Default input is about $0.42 per million tokens.",
    pricingHint: "Marked estimated when cost is omitted.",
    inputRate: "Input USD / million tok",
    outputRate: "Output USD / million tok",
    lowThreshold: "Low-balance threshold",
    save: "Save settings",
    clearKey: "Clear API key",
    billingTitle: "Usage",
    billingIntro: "One row per call. Balance appears only when the API returns it.",
    billingIntroLaya: "Local, no token charge.",
    insufficient: "TypeSafe credits are insufficient (HTTP 402).",
    lowBalance: (credits) => `Balance is below the threshold${credits == null ? "" : ` (${credits} left)`}.`,
    loadingUsage: "Loading usage…",
    emptyUsage: "No usage yet.",
    today: "Today",
    sevenDays: "7 days",
    allTime: "All time",
    callsTok: (calls, tokens, kind) => `${calls} calls · ${tokens} tok${kind ? ` · ${kind}` : ""}`,
    creditsLeft: "Credits left",
    creditsMissing: "API did not return",
    creditsAt: "Latest balance",
    ledger: "Call ledger",
    loadingLedger: "Loading ledger…",
    emptyLedger: "Ledger is empty.",
    emptyLedgerLaya: "No Laya calls yet.",
    colTime: "Time",
    colResult: "Result",
    colModel: "Model",
    colInput: "Input",
    colOutput: "Output",
    colSpend: "Spend",
    colBalance: "Balance",
    success: "OK",
    failed: "Failed",
    prev: "Previous",
    next: "Next",
  },
  billing: {
    insufficient: "TypeSafe credits are insufficient (HTTP 402). Top up before continuing analysis.",
    view: "View billing",
    low: (credits) => `TypeSafe balance is low${credits != null ? ` (${credits} left)` : ""}.`,
    chipAria: "Usage and billing",
    engineJev: "Jev",
    engineLaya: "Laya",
    layaFree: "local · no charge",
    pastJev: "Past Jev",
    today: "Today",
    balance: "Balance",
    balanceMissing: "not returned",
    kindActual: "Official",
    kindMixed: "Mixed",
    kindEstimate: "Estimated",
  },
};

export const messages: Record<Locale, Messages> = {
  "zh-Hant": zhHant,
  "zh-Hans": zhHans,
  en,
};
