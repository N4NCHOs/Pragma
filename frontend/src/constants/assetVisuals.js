// The API only returns asset_id/name/ticker — branding (badge color + glyph)
// and the short blurb shown on Coin Detail aren't backend data, so they live
// here as a small frontend-only lookup.
const ASSET_VISUALS = {
  asset_btc: {
    glyph: "₿",
    color: "#f7931a",
    description: "The original cryptocurrency and the largest by market cap, often treated as a store of value.",
  },
  asset_eth: {
    glyph: "Ξ",
    color: "#627eea",
    description: "A programmable blockchain that powers most smart contracts, DeFi, and NFT activity.",
  },
  asset_usdt: {
    glyph: "₮",
    color: "#26a17b",
    description: "The largest stablecoin, pegged 1:1 to the US dollar and widely used for trading and payments.",
  },
  asset_bnb: {
    glyph: "◆",
    color: "#d4a017",
    description: "The native token of the Binance exchange and BNB Chain ecosystem.",
  },
  asset_xrp: {
    glyph: "✕",
    color: "#3aa6e0",
    description: "A token built for fast, low-cost cross-border payments, issued by Ripple Labs.",
  },
  asset_usdc: {
    glyph: "$",
    color: "#2775ca",
    description: "A dollar-pegged stablecoin issued by Circle, popular in DeFi and institutional settlement.",
  },
  asset_sol: {
    glyph: "◎",
    color: "#9945ff",
    description: "A high-throughput blockchain known for low fees and fast confirmation times.",
  },
  asset_trx: {
    glyph: "▼",
    color: "#eb0029",
    description: "A blockchain platform focused on content sharing and high-volume stablecoin transfers.",
  },
  asset_doge: {
    glyph: "Ð",
    color: "#c2a633",
    description: "A meme-originated cryptocurrency with a large, active retail community.",
  },
  asset_hype: {
    glyph: "H",
    color: "#1b3a8a",
    description: "The native token of the Hyperliquid perpetuals exchange.",
  },
};

const FALLBACK_VISUAL = { glyph: "●", color: "#6b7182", description: "" };

export function getAssetVisual(assetId) {
  return ASSET_VISUALS[assetId] || FALLBACK_VISUAL;
}

export default ASSET_VISUALS;
