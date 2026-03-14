# Google Alerts Setup — Viper Inbound Engine

## Instructions for Jordan

### Step 1: Go to Google Alerts
https://www.google.com/alerts

Make sure you're logged into your Google account.

### Step 2: Create Each Alert

For EACH keyword string below:
1. Paste the keyword into the search box
2. Click "Show options"
3. Set these settings:
   - **How often:** As-it-happens
   - **Sources:** Automatic
   - **Language:** English
   - **Region:** United States
   - **How many:** All results
   - **Deliver to:** RSS feed
4. Click "Create Alert"
5. After creating, click the RSS icon next to the alert to get the RSS feed URL
6. Copy the RSS feed URL and save it

### Step 3: Save All RSS URLs

After creating all 25 alerts, paste each RSS feed URL into:
`~/polymarket-bot/viper/inbound/rss_feeds.json`

---

## 25 Keyword Strings (copy-paste each one)

```
1.  "need a chatbot" small business
2.  "looking for chatbot" dentist OR dental OR HVAC OR lawyer
3.  "want to automate" customer service small business
4.  "missed calls" dentist OR dental practice
5.  "after hours" answering service dental OR HVAC OR law firm
6.  "chatbot for" dentist OR "dental practice" OR "law firm"
7.  "hire chatbot developer" OR "chatbot agency"
8.  "looking for AI" automation agency
9.  "losing leads" HVAC OR plumber OR dentist
10. "no one answers the phone" dentist OR lawyer OR contractor
11. "can't keep up with leads" real estate OR dental
12. "dental practice" AI automation
13. "law firm" chatbot implementation
14. "HVAC business" automation customer service
15. "real estate agent" AI chatbot lead
16. "property management" chatbot tenant communication
17. "need automation" small business
18. "chatbot developer needed"
19. "AI for my business" small business
20. "appointment scheduling bot" OR "booking automation"
21. "patient scheduling" automation dental
22. "client intake" automation law firm
23. "after hours" leads real estate
24. "virtual receptionist" dentist OR HVAC OR lawyer
25. "answering service replacement" AI OR chatbot
```

---

## How to Get the RSS Feed URL

After creating each alert:
1. Go back to https://www.google.com/alerts
2. You'll see all your alerts listed
3. Next to each alert, click the pencil/edit icon
4. Change "Deliver to" to "RSS feed" if not already set
5. Click the RSS icon (orange icon) that appears next to the alert
6. Copy the URL from your browser — it will look like:
   `https://www.google.com/alerts/feeds/XXXXX/YYYYY`
7. Paste it into rss_feeds.json

## Time Estimate
~15-20 minutes to create all 25 alerts.
