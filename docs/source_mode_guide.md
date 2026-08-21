# PDF Source Mode — उपयोग की सरल गाइड

## 1. Source group तैयार करें

एक private Telegram group बनाकर उसका chat ID `.env` में `SOURCE_GROUP_ID` के रूप में रखें। Bot को उस group में add करें और administrator बनाएं। PDF files bot को add करने के बाद इसी एक configured group में भेजें। दूसरे किसी group से PDF स्वीकार नहीं होगी।

सिर्फ `ADMIN_USER_IDS` में मौजूद global bot admins की PDF स्वीकार की जाती है। उस group के सामान्य owner/admin या सामान्य member की PDF source bank में नहीं जाएगी। पहले से भेजी गई पुरानी files Bot API की history से अपने-आप नहीं मिलतीं; उन्हें bot add होने के बाद दोबारा forward करना होगा।

## 2. PDF upload करें

Admin PDF भेजेगा। Bot file download करके पूछेगा:

1. State या All India चुनें।
2. Subject चुनें।

इसके बाद bot PDF को पढ़कर pages और sections में बांटेगा। Text PDF सीधे पढ़ी जाती है। Scanned/image PDF के लिए `SOURCE_OCR_ENABLED=true` और server पर OCR tools चाहिए। OCR न मिले तो bot PDF को failed mark करेगा; वह अनुमान लगाकर text नहीं बनाएगा।

## 3. Automatic source selection

अब settings में Source Mode के अलग buttons नहीं हैं। Bot अपने-आप group या DM की state, subject और topic के matching indexed PDF chunks खोजेगा। Matching PDF उपलब्ध होने पर question उसी source से बनाया जाएगा और source title/page citation दिखेगा। Source उपलब्ध न होने पर bot सामान्य syllabus-grounded Practice Mode पर चला जाएगा। User को कोई mode manually चुनने की जरूरत नहीं है।

Source selection के बाद भी existing difficulty, language, topic rotation, validator और no-repeat checks लागू रहते हैं।

## 4. Source attribution

Source-grounded question के explanation या long question card में PDF filename और page range दिखेगा। Question database में source document, source state, subject, page range और chunk hash भी सुरक्षित रहता है।

## 5. Commands

- `/sources` — indexed PDFs की स्थिति और section count देखना.
- `/settings` — सामान्य group या DM settings बदलना.

## 6. Environment variables

```env
SOURCE_STORAGE_DIR=source_storage
SOURCE_MAX_PDF_MB=50
SOURCE_OCR_ENABLED=false
SOURCE_GROUP_ID=-1001234567890
```

Source chunks PostgreSQL में persist किए जाते हैं। Raw PDFs local storage में रहती हैं और reprocessing के लिए जरूरी होती हैं। Render deployment में ephemeral filesystem पर निर्भर न रहें; paid persistent disk या S3/R2 जैसी persistent object storage लगाएं। `SOURCE_STORAGE_DIR` को उस mounted storage path पर सेट करें।

## 7. Copyright और accuracy

Commercial guide books या copyrighted material को बिना अनुमति copy करके distribute न करें। Official/public or licensed PDFs का उपयोग करें। Source Mode question को भी independent validator और structural checks से pass होना होगा। Bot किसी AI-generated question को वास्तविक previous-year question नहीं बताएगा जब तक official source से verified न हो।
