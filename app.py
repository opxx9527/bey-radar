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
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage

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
# 🌊 全網貼文海巡探測器 (包含圖片網址抓取嘗試)
# ======================
def search_all_threads_posts(query_word):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    search_url = f"https://www.google.com/search?q=site:threads.net+{query_word}&tbs=qdr:w" 
    results = []
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code != 200: return results
        html = response.text
        
        matches = re.findall(r'threads\.net/post/([^"&?\s>/]+)', html)
        snippets = re.findall(r'<div[^>]*class="[^"]*(?:BNeawe|kvH3be|jSuv6c)[^"]*"[^>]*>(.*?)</div>', html)
        
        # 嘗試從搜尋頁中捞取潛在的圖片縮圖
        img_urls = re.findall(r'src="(https://encrypted-tbn[^"]+)"', html)
        
        unique_matches = list(set(matches))
        for idx, post_code in enumerate(unique_matches[:10]):
            post_url = f"https://www.threads.net/post/{post_code}"
            snippet_text = snippets[idx] if idx < len(snippets) else "點擊連結查看詳細內容"
            snippet_text = re.sub(r'<[^>]+>', '', snippet_text)
            
            # 如果有抓到對應的縮圖，就帶給 AI 一起看
            associated_img = img_urls[idx] if idx < len(img_urls) else None
            
            results.append({
                "snippet": snippet_text,
                "url": post_url,
                "img_url": associated_img
            })
    except Exception as e:
        print(f"全網搜捕異常: {e}")
    return results

# ======================
# AI 視覺與語意雙重審查機制 (海巡專用)
# ======================
def parse_post_with_ai(snippet, img_url=None):
    if not model: return None
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    prompt = (
        f"你是一個具備視覺與文字辨識能力的戰鬥陀螺比賽雷達 AI。現在時間是：{current_time}。\n"
        f"請審查以下這段從 Threads 全網撈到的貼文資料：\n"
        f"【文字內容】：「{snippet}」\n"
    )
    
    contents = []
    # 如果海巡有撈到潛在的貼文海報圖片，就把圖片下載並餵給 Gemini 
    if img_url:
        prompt += "【附帶海報圖片】我已經附上了這篇貼文對應的活動海報縮圖，請同時辨識圖片中的文字。\n"
        try:
            img_response = requests.get(img_url, timeout=5)
            if img_response.status_code == 200:
                contents.append({"mime_type": "image/jpeg", "data": img_response.content})
        except Exception:
            pass
            
    prompt += (
        f"\n【任務指令】\n"
        f"1. 判斷這是不是舉辦在台灣「台南」的戰鬥陀螺比賽或聚會活動。\n"
        f"2. 請綜合文字與海報圖片中的所有資訊，提煉出最完整的比賽細節。\n"
        f"3. 必須以嚴格的 JSON 格式回傳（絕對不要加上 ```json 這樣的 markdown 標籤，只要純字串）。\n"
        f"格式：{{\"is_tainan_bey\": true, \"match_time\": \"活動時間\", \"location\": \"地點\", \"details\": \"活動簡述（包含組別或報名費等）\"}}\n"
        f"4. 如果不是台南的陀螺比賽，請回傳：{{\"is_tainan_bey\": false}}"
    )
    
    contents.append(prompt)
    
    try:
        response = model.generate_content(contents)
        text = response.text.strip()
        tb = '`' + '`' + '`'
        if text.startswith(tb + "json"): text = text[len(tb)+4 : -len(tb)].strip()
        elif text.startswith(tb): text = text[len(tb) : -len(tb)].strip()
        return json.loads(text)
    except Exception:
        return None

# ======================
# 核心：海巡主邏輯
# ======================
def run_real_sea_patrol():
    conn = sqlite3.connect('seen_urls.db')
    c = conn.cursor()
    raw_posts = search_all_threads_posts("台南+戰鬥陀螺+比賽")
    new_finds = []
    
    for p in raw_posts:
        url = p["url"]
        c.execute("SELECT * FROM urls WHERE url=?", (url,))
        if c.fetchone() is not None: continue
        c.execute("INSERT INTO urls (url) VALUES (?)", (url,))
        
        info = parse_post_with_ai(p["snippet"], p.get("img_url"))
        
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
            line_bot_api.broadcast(TextSendMessage(text="🌊 【真·全網絡人貼文海巡】回報！\n經 AI 視覺與語意篩選，發現最新賽事：\n\n" + "\n\n---\n\n".join(new_finds)))
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

# ======================
# 1. 處理 LINE 文字訊息
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    if "除錯" in user_text:
        reply = "🟢 海巡與多模態視覺引擎就緒！\n1
