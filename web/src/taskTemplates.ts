/** Built-in task templates. Name and prompt follow the UI locale at the moment a chip is picked. */

import type { Locale } from "./i18n/messages";

export interface BuiltinTaskTemplate {
  id: string;
  name: string;
  prompt: string;
}

const zhHant: readonly BuiltinTaskTemplate[] = [
  {
    id: "wool",
    name: "媷羊毛與福利",
    prompt: [
      "判斷這則訊息是否符合下列薅羊毛／福利收錄，且沒有觸及剔除標準。",
      "沒有地區限制、或亞洲地區用戶也能參加的都算；只限香港的產品都算，因為香港屬於亞洲；排除亞洲的優惠不算。",
      "",
      "【收錄類別】",
      "1. 信用卡/扣帳卡：新卡優惠、高額回贈（cashback）、里數/積分優惠、免年費條件",
      "2. 銀行：開戶獎賞、存款利率優惠、跨境轉帳優惠",
      "3. 支付工具（支付寶/AlipayHK/WeChat Pay/Octopus/PayMe 等）：新用戶優惠、商戶折扣、儲值獎賞；其他全球或亞洲支付工具的同類福利都算",
      "4. Staking/持幣：主流幣（BTC/ETH/SOL 等）staking 年化（APY）、鎖倉條件、平台可信度",
      "5. Web3 定存/理財福利：CeFi/DeFi 定存產品、年化收益、平台風險評級",
      "6. 新出信用卡/扣帳卡（APY 型或高反現）：例如虛擬銀行、金融科技卡發行的高息/高反現產品",
      "7. eSIM/電話卡：平價保號方案、漫遊套餐優惠，沒有地區限制、或亞洲用戶都能買的都算",
      "8. 鏈上身份福利：例如錢包地址持有記錄、鏈上活動證明（POAP 等）帶來的白名單/空投資格",
      "9. NFT：低價/免費獲取、未來有實際效用或回報預期的項目（非純炒作）",
      "10. 新鏈活動/空投：新公鏈測試網任務、生態活動，沒有地區限制、或亞洲用戶都能參加的都算",
      "",
      "【剔除標準】",
      "- 需要先存入大額資金才有資格的（高風險局）",
      "- 平台未經審核/上線少於 3 個月/無審計報告的 DeFi 或交易所",
      "- 需要洩露 KYC/身分證資料換取小額回饋",
      "- 明顯是推薦碼/傳銷式獎賞結構（拉人頭才有回報）",
      "- 過期或即將過期（少於 48 小時）的優惠，除非特別註明「急件」",
      "",
      "無關閒聊、純價格波動、重複轉發不算。",
    ].join("\n"),
  },
  {
    id: "crypto-major",
    name: "crypto重大消息",
    prompt:
      "判斷這則訊息是否為加密貨幣的重大消息。相關包括主流幣或重要協議的劇烈漲跌、交易所故障或倒閉、監管或 ETF 決定、大型駭客、脫錨、主流鏈停擺。日常小幅波動、迷因幣喊單、沒有新事實的轉發不算。",
  },
  {
    id: "cloud-resident",
    name: "雲居民福利資訊",
    prompt:
      "判斷這則訊息是否是給雲居民的福利或實用資訊。相關包括優惠、免費額度、補貨、邀請獎勵、節點、白名單，以及明確的領取方式。與雲居民福利無關的閒聊和其他專案不算。",
  },
  {
    id: "stock-directional",
    name: "{某股票}的利好消息或負面消息",
    prompt:
      "使用者會把名稱和本段裡的「某股票」換成要追蹤的股票代碼或公司名。判斷這則訊息是否在談這檔股票，而且是利好（業績、訂單、政策支持、增持、上調）或負面（虧損、調查、減持、下調、事故、訴訟）。其他股票、沒有方向的純行情、無關大盤閒聊不算。",
  },
  {
    id: "airdrop-testnet",
    name: "空投與測試網",
    prompt:
      "判斷這則訊息是否為還能參與的空投、測試網、互動任務或積分活動。要有做法、時間或連結才算相關。已結束、純喊單、沒有參加方式的不算。無關閒聊、純價格波動、重複轉發不算。",
  },
  {
    id: "exchange-listing",
    name: "交易所上幣與下架",
    prompt:
      "判斷這則訊息是否為交易所新上幣、開盤、下架、暫停充提或交易對變更，且點名了幣種或交易對。沒有點名對象的泛稱行情不算。無關閒聊、純價格波動、重複轉發不算。",
  },
  {
    id: "scam-alert",
    name: "詐騙與安全警訊",
    prompt:
      "判斷這則訊息是否在警告詐騙、釣魚、假空投、盜幣、私鑰外洩、惡意授權或合約風險，且有具體對象或手法。沒有對象的泛泛提醒不算。無關閒聊、純價格波動、重複轉發不算。",
  },
];

const zhHans: readonly BuiltinTaskTemplate[] = [
  {
    id: "wool",
    name: "薅羊毛与福利",
    prompt: [
      "判断这则消息是否符合下列薅羊毛／福利收录，且没有触及剔除标准。",
      "没有地区限制、或亚洲地区用户也能参加的都算；只限香港的产品都算，因为香港属于亚洲；排除亚洲的优惠不算。",
      "",
      "【收录类别】",
      "1. 信用卡/扣账卡：新卡优惠、高额回赠（cashback）、里数/积分优惠、免年费条件",
      "2. 银行：开户奖赏、存款利率优惠、跨境转账优惠",
      "3. 支付工具（支付宝/AlipayHK/WeChat Pay/Octopus/PayMe 等）：新用户优惠、商户折扣、储值奖赏；其他全球或亚洲支付工具的同类福利都算",
      "4. Staking/持币：主流币（BTC/ETH/SOL 等）staking 年化（APY）、锁仓条件、平台可信度",
      "5. Web3 定存/理财福利：CeFi/DeFi 定存产品、年化收益、平台风险评级",
      "6. 新出信用卡/扣账卡（APY 型或高反现）：例如虚拟银行、金融科技卡发行的高息/高反现产品",
      "7. eSIM/电话卡：平价保号方案、漫游套餐优惠，没有地区限制、或亚洲用户都能买的都算",
      "8. 链上身份福利：例如钱包地址持有记录、链上活动证明（POAP 等）带来的白名单/空投资格",
      "9. NFT：低价/免费获取、未来有实际效用或回报预期的项目（非纯炒作）",
      "10. 新链活动/空投：新公链测试网任务、生态活动，没有地区限制、或亚洲用户都能参加的都算",
      "",
      "【剔除标准】",
      "- 需要先存入大额资金才有资格的（高风险局）",
      "- 平台未经审核/上线少于 3 个月/无审计报告的 DeFi 或交易所",
      "- 需要泄露 KYC/身份证资料换取小额回馈",
      "- 明显是推荐码/传销式奖赏结构（拉人头才有回报）",
      "- 过期或即将过期（少于 48 小时）的优惠，除非特别注明「急件」",
      "",
      "无关闲聊、纯价格波动、重复转发不算。",
    ].join("\n"),
  },
  {
    id: "crypto-major",
    name: "crypto重大消息",
    prompt:
      "判断这则消息是否为加密货币的重大消息。相关包括主流币或重要协议的剧烈涨跌、交易所故障或倒闭、监管或 ETF 决定、大型黑客、脱锚、主流链停摆。日常小幅波动、迷因币喊单、没有新事实的转发不算。",
  },
  {
    id: "cloud-resident",
    name: "云居民福利资讯",
    prompt:
      "判断这则消息是否是给云居民的福利或实用信息。相关包括优惠、免费额度、补货、邀请奖励、节点、白名单，以及明确的领取方式。与云居民福利无关的闲聊和其他项目不算。",
  },
  {
    id: "stock-directional",
    name: "{某股票}的利好消息或负面消息",
    prompt:
      "使用者会把名称和本段里的「某股票」换成要追踪的股票代码或公司名。判断这则消息是否在谈这档股票，而且是利好（业绩、订单、政策支持、增持、上调）或负面（亏损、调查、减持、下调、事故、诉讼）。其他股票、没有方向的纯行情、无关大盘闲聊不算。",
  },
  {
    id: "airdrop-testnet",
    name: "空投与测试网",
    prompt:
      "判断这则消息是否为还能参与的空投、测试网、互动任务或积分活动。要有做法、时间或链接才算相关。已结束、纯喊单、没有参加方式的不算。无关闲聊、纯价格波动、重复转发不算。",
  },
  {
    id: "exchange-listing",
    name: "交易所上币与下架",
    prompt:
      "判断这则消息是否为交易所新上币、开盘、下架、暂停充提或交易对变更，且点名了币种或交易对。没有点名对象的泛称行情不算。无关闲聊、纯价格波动、重复转发不算。",
  },
  {
    id: "scam-alert",
    name: "诈骗与安全警示",
    prompt:
      "判断这则消息是否在警告诈骗、钓鱼、假空投、盗币、私钥外泄、恶意授权或合约风险，且有具体对象或手法。没有对象的泛泛提醒不算。无关闲聊、纯价格波动、重复转发不算。",
  },
];

const en: readonly BuiltinTaskTemplate[] = [
  {
    id: "wool",
    name: "Airdrops and perks",
    prompt: [
      "Decide whether this message fits the airdrop and perk categories below, and does not meet an exclusion.",
      "A message counts when the offer has no region restriction, or users in Asia can join; Hong Kong-only products still count because Hong Kong is in Asia; offers that exclude Asia do not count.",
      "",
      "【Inclusion categories】",
      "1. Credit / debit cards: new-card offers, high cashback, miles or points offers, annual-fee waivers",
      "2. Banks: account-opening rewards, deposit-rate offers, cross-border transfer offers",
      "3. Payment tools (Alipay/AlipayHK/WeChat Pay/Octopus/PayMe and similar): new-user offers, merchant discounts, stored-value rewards; other global or Asian payment perks also count",
      "4. Staking / holding: staking APY on major coins (BTC/ETH/SOL and similar), lock-up terms, platform trustworthiness",
      "5. Web3 fixed deposits / yield perks: CeFi/DeFi fixed-deposit products, annualized yield, platform risk rating",
      "6. Newly issued credit / debit cards (APY-style or high cashback): for example high-interest or high-cashback products issued by virtual banks and fintech cards",
      "7. eSIM / phone plans: cheap number-keeping and roaming plans with no region limit, or that Asian users can buy",
      "8. On-chain identity perks: for example whitelist or airdrop eligibility from wallet-address holding history or on-chain activity proofs (POAP and similar)",
      "9. NFT: low-price or free acquisition of projects expected to have real utility or return (not pure speculation)",
      "10. New-chain campaigns / airdrops: testnet tasks and ecosystem campaigns with no region limit, or that Asian users can join",
      "",
      "【Exclusion criteria】",
      "- Requires depositing a large sum before you qualify (high-risk setup)",
      "- DeFi protocols or exchanges that are unvetted, have been live for under 3 months, or have no audit report",
      "- Requires leaking KYC or identity-document data in exchange for a small reward",
      "- Clearly a referral-code or MLM-style reward structure (you are paid only for recruiting people)",
      "- Expired offers, or offers expiring in under 48 hours, unless specifically marked urgent",
      "",
      "Unrelated chat, bare price moves, and duplicate reposts do not count.",
    ].join("\n"),
  },
  {
    id: "crypto-major",
    name: "Major crypto news",
    prompt:
      "Decide whether this message is major cryptocurrency news. That includes sharp moves in major coins or important protocols, exchange outages or failures, regulation or ETF decisions, large hacks, depegs, and major-chain halts. Small day-to-day moves, meme-coin shilling, and reposts with no new facts do not count.",
  },
  {
    id: "cloud-resident",
    name: "Cloud-resident perks",
    prompt:
      "Decide whether this message is a perk or useful notice for cloud residents. That includes discounts, free quota, restocks, referral rewards, nodes, whitelists, and a clear way to claim them. Chat unrelated to cloud-resident perks, and other projects, do not count.",
  },
  {
    id: "stock-directional",
    name: "{a stock}: good or bad news",
    prompt:
      'Replace "{a stock}" in the task name and in this prompt with the ticker or company name to track. Decide whether this message is about that stock and is either good news (earnings, orders, policy support, increased holdings, upgrades) or bad news (losses, investigations, reduced holdings, downgrades, accidents, lawsuits). Other stocks, directionless price ticks, and unrelated market chat do not count.',
  },
  {
    id: "airdrop-testnet",
    name: "Airdrops and testnets",
    prompt:
      "Decide whether this message is an airdrop, testnet, interactive task, or points campaign that people can still join. It counts only when it includes how to take part, a time, or a link. Ended campaigns, pure shilling, and posts with no way to join do not count. Unrelated chat, bare price ticks, and duplicate reposts do not count.",
  },
  {
    id: "exchange-listing",
    name: "Exchange listings and delistings",
    prompt:
      "Decide whether this message is a new exchange listing, market open, delisting, deposit or withdrawal pause, or trading-pair change, and it names the coin or pair. Generic market talk that names no asset does not count. Unrelated chat, bare price ticks, and duplicate reposts do not count.",
  },
  {
    id: "scam-alert",
    name: "Scams and security alerts",
    prompt:
      "Decide whether this message warns about a scam, phishing, a fake airdrop, stolen funds, a private-key leak, a malicious approval, or contract risk, and it names a specific target or method. Vague reminders with no target do not count. Unrelated chat, bare price ticks, and duplicate reposts do not count.",
  },
];

const BY_LOCALE: Record<Locale, readonly BuiltinTaskTemplate[]> = {
  "zh-Hant": zhHant,
  "zh-Hans": zhHans,
  en,
};

export function builtinTaskTemplates(locale: Locale): readonly BuiltinTaskTemplate[] {
  return BY_LOCALE[locale] ?? zhHant;
}
