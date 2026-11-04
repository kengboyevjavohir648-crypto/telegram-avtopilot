# Telegram kanal avtopiloti: o'rnatish bo'yicha qo'llanma

Bot **@Javohiraipro** kanalini 24/7 yuritadi. Kompyuteringiz o'chiq bo'lsa ham ishlaydi, chunki GitHub serverida bepul ishga tushadi.

## Nima qiladi

| Vaqt (Toshkent) | Ish |
|---|---|
| 09:00 | 📰 2 ta AI yangiligi (inglizcha saytlardan olib, o'zbekchaga o'giradi) |
| 12:30 | 💡 AI vositasi yoki maslahat |
| 15:00 | 🗓 `content/navbat/` papkasidagi navbatdagi post |
| 18:00 | 📰 2 ta AI yangiligi |
| 20:00 | 🎬 `content/reels/` papkasidagi navbatdagi video |

**Har bir post avval sizga Telegram'da keladi.** ✅ bossangiz kanalga chiqadi, ❌ bossangiz bekor bo'ladi.
Botga o'zingiz matn, rasm yoki video yuborsangiz, uni ham kanalga chiqarishni taklif qiladi.

> ⏱ Bot har 15 daqiqada uyg'onadi, shuning uchun tugma bosilgach post 5-20 daqiqada chiqadi. Bu normal.

Vaqtlarni o'zgartirish uchun `config.json` dagi `schedule` qismini tahrirlang.

---

## 1-qadam. Bot yaratish (2 daqiqa)

1. Telegram'da **@BotFather** ga kiring → `/newbot` yozing.
2. Botga nom bering (masalan `Javohir AI Yordamchi`) va username bering (oxiri `bot` bilan tugashi shart, masalan `javohir_ai_post_bot`).
3. BotFather sizga **token** beradi (`123456:ABC...` ko'rinishida). Uni hech kimga bermang, 4-qadamda kerak bo'ladi.
4. Botingizni oching va **Start** bosing.

## 2-qadam. Botni kanalga admin qilish

Kanal → ⚙️ Boshqarish → **Administratorlar** → Admin qo'shish → botingiz username'ini qidiring → faqat **"Xabar joylash"** huquqini yoqing → Saqlash.

## 3-qadam. Gemini kaliti (bepul, tavsiya etiladi)

Kalitsiz ham ishlaydi, lekin unda yangiliklar Google Translate bilan o'giriladi va matn g'aliz chiqadi. Gemini bilan postlar jonli o'zbek tilida yoziladi.

1. **aistudio.google.com/apikey** saytiga Google akkauntingiz bilan kiring.
2. **Create API key** bosing va kalitni nusxalang.

## 4-qadam. GitHub'ga joylash

1. **github.com** da akkaunt oching (bepul).
2. Yuqori o'ngdagi **+** → **New repository**:
   - Nomi: `telegram-avtopilot`
   - **Public** ni tanlang (Public repoda GitHub Actions cheksiz bepul. Private'da oyiga 2000 daqiqa limit bor va bot uni yetkazolmaydi. Token va kalitlar baribir yashirin "Secrets" ichida turadi, ularni hech kim ko'rmaydi.)
   - **Create repository** bosing.
3. Ochilgan sahifada **"uploading an existing file"** havolasini bosing. `telegram_bot` papkasidagi **hamma narsani** (`bot.py`, `config.json`, `requirements.txt`, `state.json`, `.gitignore`, `content` papkasi) sudrab tashlang → **Commit changes**.
4. `.github` papkasi yashirin bo'lgani uchun brauzer uni yuklamasligi mumkin. Shuning uchun uni qo'lda yarating:
   **Add file → Create new file** → nom maydoniga aynan `.github/workflows/telegram.yml` deb yozing → kompyuterdagi `telegram_bot\.github\workflows\telegram.yml` faylining ichidagini nusxalab qo'ying → **Commit changes**.

## 5-qadam. Sirlarni kiritish

Repo → **Settings** → chapda **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Secret |
|---|---|
| `BOT_TOKEN` | BotFather bergan token |
| `GEMINI_API_KEY` | 3-qadamdagi kalit (ixtiyoriy) |
| `ADMIN_ID` | hozircha bo'sh qoldiring, 6-qadamda qo'shasiz |

## 6-qadam. Ishga tushirish va ADMIN_ID ni olish

1. Repo → **Actions** bo'limi → "I understand my workflows, enable them" tugmasi chiqsa bosing.
2. Botingizga Telegram'da `/start` yozing.
3. Actions → **Telegram avtopilot** → **Run workflow** bosing va 1 daqiqa kuting.
4. Bot sizga **Telegram ID** ingizni yozadi (raqam). Uni 5-qadamdagidek `ADMIN_ID` nomli secret qilib qo'shing.
5. Yana **Run workflow** bosing, keyin botga `/maslahat` yozing. Keyingi ishga tushishda sizga birinchi qoralama keladi. ✅ bosib sinab ko'ring.

Tayyor! Endi bot har 15 daqiqada o'zi ishlaydi.

---

## Kundalik foydalanish

**Bot buyruqlari:** `/yangilik`, `/maslahat`, `/reels`, `/navbat`, `/holat`.

**Yangi reels qo'shish:** GitHub'da `content/reels/` → Add file → Upload files:
- `05_nomi.mp4` (50 MB dan kichik bo'lsin, `_instagram.mp4` siqilgan versiyasi mos keladi)
- `05_nomi.txt`: video ostidagi matn

Fayllar nom tartibida chiqadi.

**Rejalashtirilgan post:** `content/navbat/` ga `.txt` fayl qo'shing. Namunasi `_namuna.txt` faylida bor.
Birinchi qatorga `vaqt: 2026-11-10 10:00` yozsangiz, post aynan shu vaqtda keladi.

**Yangi maslahatlar:** `content/maslahatlar.json` dagi 10 ta tayyor post tugagach, Gemini yangisini o'zi yozadi.

**Yangilik manbalari:** `config.json` → `news_feeds` ro'yxatiga istalgan RSS manzilini qo'shishingiz mumkin.

## Muammo bo'lsa

- **Bot jim:** Actions bo'limida oxirgi ishga tushishni oching. Qizil ❌ bo'lsa, xato matnini Claude'ga yuboring.
- **"chat not found" xatosi:** bot kanalda admin emas (2-qadam).
- **Hech narsa ishga tushmayapti:** GitHub jadvalli ishlarni ba'zan 10-20 daqiqa kechiktiradi, ayniqsa birinchi kuni.
