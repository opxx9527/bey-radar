from flask import Flask, request, abort
import os
import requests
import sqlite3
import json
import re
from datetime import datetime
import google.generativeai as genai

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# ======================
# 環境變數設定
# ======================
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") 

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Gemini 初始化失敗: {e}")
        model = None
else:
    model = None

# ======================
# 初始化 SQLite 資料庫
# ======================
def init_db():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS urls (url TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

# ======================
# 🌊 真正跨過 API 限制的「全網貼文海巡探測器」
# ======================
def search_all_threads_posts(query_word):
    """
    利用公開搜尋入口，繞過 Scraper 只能搜用戶的限制，
    直接對全網公開的 Threads 貼文內文進行地毯式搜索。
    """
    # 建立一個模擬真實瀏覽器的 Header，直接向公開網絡檢索貼文
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # 使用開放式結構入口，將關鍵字（如：台南 戰鬥陀螺 比賽）丟進去
    search_url = f"https://www.google.com/search?q=site:threads.net+{query_word}&tbs=qdr:w" 
    # 💡 tbs=qdr:w 代表嚴格限制「只爬取最近 1 週內」的最新鮮貼文，完美符合雷達即時監控！
    
    results = []
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return results
            
        html = response.text
        
        # 使用正規表達式，把所有夾帶 threads.net/post/ 的路人貼文代碼全部肉眼扒出來
        matches = re.findall(r'threads\.net/post/([^"&?\s>/]+)', html)
        
        # 抓取畫面上的文字片段（路人們發的內文摘要）
        snippets = re.findall(r'<div[^>]*class="[^"]*(?:BNeawe|kvH3be|jSuv6c)[^"]*"[^>]*>(.*?)</div>', html)
        
        unique_matches = list(set(matches))
        for idx, post_code in enumerate(unique_matches[:10]): # 每次精選前 10 筆最新路人動態
            post_url = f"https://www.threads.net/post/{post_code}"
            
            # 建立大數據摘要
            snippet_text = snippets[idx] if idx < len(snippets) else "點擊連結查看路人詳細貼文內容"
            # 移除 html 標籤
            snippet_text = re.sub(r'<[^>]+>', '', snippet_text)
            
            results.append({
                "snippet": snippet_text,
                "url": post_url
            })
    except Exception as e:
        print(f"全網搜捕異常: {e}")
        
    return results

# ======================
# AI 嚴格審查機制 (Gemini)
# ======================
def parse_post_with_ai(snippet):
    if not model: return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    prompt = (
        f"你是一個專門抓取地方比賽的 AI 雷達。現在時間是：{current_time}。\n"
        f"請審查以下這段從 Threads 全網撈到的路人貼文片段：\n"
        f"「{snippet}」\n\n"
        f"【審查任務】\n"
        f"1. 這是不是一個舉辦在台灣「台南」的戰鬥陀螺比賽、店家賽、俱樂部或聚會？\n"
        f"2. 不管它是官方公告，還是「一般個人路人帳號」發的日常碎碎念（例如：這週要去台南打陀螺、台南某某店有陀螺賽），只要確認台南有活動，就算符合！\n"
        f"3. 如果符合，請以嚴格的 JSON 格式回傳（絕對不要 markdown 標籤，只要純字串）。\n"
        f"格式：{{\"is_tainan_bey\": true, \"match_time\": \"活動時間\", \"location\": \"地點\", \"details\": \"活動簡述\"}}\n"
        f"4. 如果內容完全不符合，或根本不是台南的陀螺比賽，請回傳：{{\"is_tainan_bey\": false}}"
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        tb = '`' + '`' + '`'
        if text.startswith(tb + "json"): text = text[len(tb)+4 : -len(tb)].strip()
        elif text.startswith(tb): text = text[len(tb) : -len(tb)].strip()
        return json.loads(text)
    except Exception:
        return None

# ======================
# 真·全網海巡核心主邏輯
# ======================
def run_real_sea_patrol():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    
    # 直接用最暴力的「路人組合關鍵字」丟進去全網肉搜貼文
    raw_posts = search_all_threads_posts("台南+戰鬥陀螺+比賽")
    
    new_finds = []
    
    for p in raw_posts:
        url = p["url"]
        
        # 去重
        c.execute("SELECT * FROM urls WHERE url=?", (url,))
        if c.fetchone() is not None: continue
        
        c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
        
        # 讓 AI 鑑定路人的碎碎念
        info = parse_post_with_ai(p["snippet"])
        
        if info and info.get("is_tainan_bey"):
            msg = (
                f"🚨 【全網海巡：撈到路人情報！】\n"
                f"⏱️ 估計時間: {info.get('match_time')}\n"
                f"📍 預估地點: {info.get('location')}\n"
                f"📝 情報內容: {info.get('details')}\n"
                f"🔗 貼文直連: {url}"
            )
            new_finds.append(msg)
            
    conn.commit()
    conn.close()

    if new_finds and LINE_CHANNEL_ACCESS_TOKEN:
        try:
            line_bot_api.broadcast(TextSendMessage(text="🌊 【真·全網路人貼文海巡】回報！\n經 AI 過濾，發現以下最新台南賽事蛛絲馬跡：\n\n" + "\n\n---\n\n".join(new_finds)))
        except Exception:
            pass
            
    return len(new_finds)

# ======================
# LINE 路由控制
# ======================
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    except Exception: return "Internal Error", 500
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    if "除錯" in user_text:
        reply = "🟢 全網路人貼文海巡引擎運作中！當前策略：直接肉搜全 Threads 一週內含有「台南 戰鬥陀螺 比賽」的任何路人公開貼文，並由 Gemini 進行語意篩選。"
    elif "搜尋" in user_text or "海巡" in user_text:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🛸 正在全網搜捕所有普通路人的 Threads 碎碎念貼文，請稍候..."))
        count = run_real_sea_patrol()
        line_bot_api.broadcast(TextSendMessage(text=f"📊 海巡報告：全網普通路人貼文審查完畢，本次共捕獲 {count} 筆台南賽事情報！"))
        return
    else:
        reply = "輸入「海巡」立刻啟動全網普通路人貼文搜捕！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@app.route("/cron/scan", methods=["GET"])
def cron_scan():
    count = run_real_sea_patrol()
    return f"Patrol done. Found {count} items."

@app.route("/", methods=["GET"])
def home():
    return "Bey Radar V9.0 (Universal Post Patrol) is active! 🌊"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
