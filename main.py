from fastapi.responses import FileResponse
from fastapi import FastAPI, Request
import httpx
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from pymongo import MongoClient
import os
import json
from dotenv import load_dotenv
import re
import pandas as pd
import uuid
load_dotenv()

# ENV variables
mongo_uri = os.getenv("MONGODB_URI")
openai_api_key = os.getenv("OPENAI_API_KEY")
line_channel_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# MongoDB setup
client = MongoClient(mongo_uri)
db = client.get_database("projectlogdb")
projectmaster_collection = db["projectmaster"]
projectlog_collection = db["projectlog"]

try:
    client.admin.command("ping")
    print("✅ Connected to MongoDB!")
    
except Exception as e:
    print("❌ MongoDB connection error:", e)
    

# FastAPI app
app = FastAPI()

# สร้าง LLM chain
def get_llm_chain():
    prompt = PromptTemplate.from_template(
        "ตรวจสอบข้อความนี้ว่าเป็น 'โครงการใหม่' หรือ 'การติดตาม'\n"
        "- ถ้าเป็นโครงการใหม่ ให้แปลงข้อมูลเป็น JSON ตามโครงสร้างนี้:\n"
        "  project_no, project_name, project_date, description, contractor, supervisor\n"
        "- ถ้าเป็นการติดตาม ให้แปลงข้อมูลเป็น JSON ตามโครงสร้างนี้:\n"
        "  branch, date (YYYY-MM-DD), follow_up_no, project, address, description, next_follow_up_date (YYYY-MM-DD)\n\n"
        "ให้แปลงวันที่จาก พ.ศ. เป็น ค.ศ. โดยหัก 543 และแสดงผลในรูปแบบ YYYY-MM-DD\n"
        "ส่งกลับเฉพาะ JSON เท่านั้น ไม่ต้องอธิบายหรือใส่ข้อความอื่นใด\n\n"
        "ข้อความ: {text}"
    )
    llm = ChatOpenAI(
        temperature=0,
        model_name="gpt-4o-mini",  # หรือ gpt-3.5-turbo
        openai_api_key=openai_api_key
    )
    return prompt | llm


# Reply ไปที่ LINE
async def reply_to_line(reply_token: str, message: str):
    headers = {
        "Authorization": f"Bearer {line_channel_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message}]
    }
    async with httpx.AsyncClient() as client:
        await client.post("https://api.line.me/v2/bot/message/reply", json=payload, headers=headers)

def is_valid_name(name: str) -> bool:
    return name and name.strip() not in ["", "-", "ไม่ระบุ", "ไม่ทราบ"]

def is_valid_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"0\d{8,9}", phone.strip()))

def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email.strip()))

@app.get("/download/{filename}")
async def download_excel(filename: str):
    filepath = f"/tmp/{filename}"
    if not os.path.exists(filepath):
        return {"message": "❌ ไฟล์ไม่พบหรือหมดอายุ"}
    
    return FileResponse(
        path=filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="projectlog.xlsx"
    )
    
# Webhook endpoint
@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()
    events = body.get("events", [])
    print(events)
    for event in events:
        if event["type"] == "message" and event["message"]["type"] == "text":
            text = event["message"]["text"]
            reply_token = event["replyToken"]

            if "Upload รูปภาพโครงการ" in text:
                await reply_to_line(reply_token, "ขออภัยในความไม่สะดวก ระบบกำลังอยู่ระหว่างการพัฒนา อดใจรอซักนิดนะครับ 😉")
                
            if "แสดงข้อมูลโครงการ" in text:
                await reply_to_line(reply_token, "ขออภัยในความไม่สะดวก ระบบกำลังอยู่ระหว่างการพัฒนา อดใจรอซักนิดนะครับ 😉")
                
            # 👉 ถ้าผู้ใช้พิมพ์ "ดึงข้อมูลลูกค้า"
            if "ดึงข้อมูลลูกค้า" in text:
                customers = list(projectmaster_collection.find({}, {"_id": 0}))
                if not customers:
                    await reply_to_line(reply_token, "❌ ยังไม่มีข้อมูลลูกค้าในระบบครับ")
                else:
                    df = pd.DataFrame(customers)
                    filename = f"customers_{uuid.uuid4().hex}.xlsx"
                    filepath = f"/tmp/{filename}"
                    df.to_excel(filepath, index=False)

                    # URL บน Render ที่เปิดให้โหลด
                    download_url = f"https://fastapi-mongo-lineoa.onrender.com/download/{filename}"

                    await reply_to_line(reply_token, f"📥 ดาวน์โหลดข้อมูลลูกค้าได้ที่นี่:\n{download_url}")
                    
                continue  # ข้ามไม่ให้ประมวลผล LangChain


            # สร้าง Chain และเรียกใช้
            chain = get_llm_chain()
            result = chain.invoke({"text": text})

            try:
                match = re.search(r'\{.*\}', result.content, re.DOTALL)
                data = json.loads(match.group())

                # name = str(data.get("name", "")).strip()
                # phone = str(data.get("phone", "")).strip()
                # email = str(data.get("email", "")).strip()
                
                # if not (is_valid_name(name) and is_valid_phone(phone) and is_valid_email(email)):
                    # response_text = "❌ กรุณากรอกข้อมูลให้ครบถ้วน ชื่อ-สกุล เบอร์โทร E-mail ตัวอย่าง มานะ ใจดี 0899999999 mana_jaidee@dynastyceramic.com 😊"
                # else:
                    # บันทึกลง MongoDB
                # insert_result = projectmaster_collection.insert_one(data)
                # response_text = f"✅ บันทึกข้อมูลแล้วครับ: โครงการ: {data.get('project') or 'ไม่ทราบชื่อ'}"

            except Exception as e:
                response_text = f"❌ ไม่สามารถประมวลผลข้อมูลได้: {e}"


            # ตรวจสอบว่าคือโครงการใหม่หรือการติดตามโดยดู key json
            if "project_no" in data:
                # โครงการใหม่
                insert_result = projectmaster_collection.insert_one(data)
                response_text = f"✅ บันทึกข้อมูลแล้วครับ: โครงการ: {data.get('project_name') or 'ไม่ทราบชื่อ'}"
                
            elif "branch" in data:
                # การติดตาม
                insert_result = projectlog_collection.insert_one(data)
                response_text = f"✅ บันทึกข้อมูลการติดตามแล้วครับ: โครงการ: {data.get('project_name') or 'ไม่ทราบชื่อ'} การติดตามครั้งที่  {data.get('follow_up_no') or 'ไม่ระบุ'}"
                
            else:
                response_text = f"❌ ไม่สามารถระบุประเภทข้อมูลได้: {e}"
            
            await reply_to_line(reply_token, response_text)

    return {"status": "ok"}