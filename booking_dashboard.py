import requests
import json
from icalendar import Calendar
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
import os

NAVER_BUSINESS_ID = "893311"
NAVER_BIZ_ITEM_ID = "5027227"
AIRBNB_ICAL_URL = "https://www.airbnb.com/calendar/ical/20058964.ics?t=30d822a0fd4a4b94bb1a81f2a908eb0f&locale=ko"
DAYS_TO_SHOW = 90


def get_naver_status():
    headers = {
        "Content-Type": "application/json",
        "Referer": f"https://m.booking.naver.com/booking/13/bizes/{NAVER_BUSINESS_ID}",
        "Origin": "https://m.booking.naver.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    end = today + timedelta(days=DAYS_TO_SHOW)

    payload = {
        "operationName": "schedule",
        "variables": {
            "scheduleParams": {
                "businessId": NAVER_BUSINESS_ID,
                "bizItemId": NAVER_BIZ_ITEM_ID,
                "businessTypeId": 3,
                "startDateTime": f"{today.isoformat()}T00:00:00+09:00",
                "endDateTime": f"{end.isoformat()}T23:59:59+09:00",
                "partitionDays": DAYS_TO_SHOW + 5
            }
        },
        "query": """
        query schedule($scheduleParams: ScheduleParams) {
          schedule(input: $scheduleParams) {
            bizItemSchedule {
              daily {
                date
                summary {
                  stock
                  occupiedBookingCount
                  isBusinessDay
                  isSaleDay
                  __typename
                }
                __typename
              }
              __typename
            }
            __typename
          }
        }
        """
    }

    url = "https://m.booking.naver.com/graphql?opName=schedule"
    response = requests.post(url, headers=headers, json=payload)

    status = {}
    if response.status_code == 200:
        data = response.json()
        daily = data["data"]["schedule"]["bizItemSchedule"]["daily"]
        date_data = daily.get("date", {})

        for d, info in date_data.items():
            if not isinstance(info, dict):
                continue

            stock = info.get("stock", 0)
            booking_count = info.get("bookingCount", 0)
            is_business_day = info.get("isBusinessDay", True)
            is_sale_day = info.get("isSaleDay", True)

            if stock > 0 and booking_count >= stock:
                status[d] = "booked"
            elif not is_sale_day or not is_business_day or stock == 0:
                status[d] = "blocked"
            else:
                status[d] = "available"
    else:
        print(f"네이버 데이터 가져오기 실패: {response.status_code}")

    return status


def get_airbnb_status():
    response = requests.get(AIRBNB_ICAL_URL)
    status = {}

    if response.status_code == 200:
        cal = Calendar.from_ical(response.text)
        for component in cal.walk('VEVENT'):
            summary_text = str(component.get('summary', ''))
            start = component.get('dtstart').dt
            end = component.get('dtend').dt

            is_real_booking = "Reserved" in summary_text or "예약" in summary_text
            is_blocked = "Not available" in summary_text or "차단" in summary_text or "unavailable" in summary_text.lower()

            current = start
            while current < end:
                d = current.isoformat()
                if is_real_booking:
                    status[d] = "booked"
                elif is_blocked:
                    status[d] = "blocked"
                else:
                    status.setdefault(d, "booked")
                current = date.fromordinal(current.toordinal() + 1)
    else:
        print(f"에어비앤비 데이터 가져오기 실패: {response.status_code}")

    return status


def color_for(status):
    return {
        "available": "#d4f4dd",
        "booked": "#f9c0c0",
        "blocked": "#dcdcdc",
    }.get(status, "#ffffff")

def label_for(status):
    return {
        "available": "가능",
        "booked": "마감",
        "blocked": "차단",
    }.get(status, "-")


def build_html(naver_status, airbnb_status):
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    days = [today + timedelta(days=i) for i in range(DAYS_TO_SHOW)]

    months = {}
    for d in days:
        key = (d.year, d.month)
        months.setdefault(key, []).append(d)

    weekday_names = ["일", "월", "화", "수", "목", "금", "토"]

    month_blocks = ""
    overlap_count = 0
    overlap_dates = []
    naver_booked_count = 0
    naver_blocked_count = 0
    airbnb_booked_count = 0
    airbnb_blocked_count = 0

    for (year, month), month_days in months.items():
        first_day = month_days[0]
        start_offset = (first_day.weekday() + 1) % 7

        cells = "<div class='empty'></div>" * start_offset

        for d in month_days:
            iso = d.isoformat()
            n_status = naver_status.get(iso, "available")
            a_status = airbnb_status.get(iso, "available")

            if n_status == "booked":
                naver_booked_count += 1
            elif n_status == "blocked":
                naver_blocked_count += 1
            if a_status == "booked":
                airbnb_booked_count += 1
            elif a_status == "blocked":
                airbnb_blocked_count += 1

            is_overlap = (n_status == "booked" and a_status == "booked")
            if is_overlap:
                overlap_count += 1
                overlap_dates.append(iso)

            warn_class = "overlap" if is_overlap else ""
            overlap_badge = "<div class='overlap-badge'>⚠️ 중복</div>" if is_overlap else ""

            cells += f"""
            <div class='day {warn_class}'>
                <div class='date-num'>{d.day}</div>
                {overlap_badge}
                <div class='platform' style='background:{color_for(n_status)}'>네이버 {label_for(n_status)}</div>
                <div class='platform' style='background:{color_for(a_status)}'>에어비앤비 {label_for(a_status)}</div>
            </div>
            """

        month_blocks += f"""
        <div class='month-block'>
            <h2>{year}년 {month}월</h2>
            <div class='weekday-row'>
                {''.join(f"<div class='weekday'>{w}</div>" for w in weekday_names)}
            </div>
            <div class='calendar-grid'>
                {cells}
            </div>
        </div>
        """

    if overlap_count > 0:
        date_list_str = ", ".join(overlap_dates)
        warning_banner = f"<div class='warning-banner'>⚠️ 이중예약 의심 날짜가 {overlap_count}일 있습니다!<br><span style='font-weight:normal; font-size:13px;'>{date_list_str}</span></div>"
    else:
        warning_banner = "<div class='ok-banner'>✅ 현재 겹치는 예약이 없습니다.</div>"

    summary_box = f"""
    <div class="summary-box">
        <div class="summary-item"><span class="dot" style="background:#f9c0c0"></span>네이버 예약마감: {naver_booked_count}일</div>
        <div class="summary-item"><span class="dot" style="background:#dcdcdc"></span>네이버 예약차단: {naver_blocked_count}일</div>
        <div class="summary-item"><span class="dot" style="background:#f9c0c0"></span>에어비앤비 예약마감: {airbnb_booked_count}일</div>
        <div class="summary-item"><span class="dot" style="background:#dcdcdc"></span>에어비앤비 예약차단: {airbnb_blocked_count}일</div>
    </div>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="300">
        <title>숙소 예약 현황 대시보드</title>
        <style>
            body {{ font-family: 'Malgun Gothic', sans-serif; background: #f5f5f7; margin: 0; padding: 30px; }}
            h1 {{ text-align: center; color: #222; }}
            .updated {{ text-align: center; color: #888; margin-bottom: 20px; }}
            .warning-banner {{ background: #ffe0e0; border: 2px solid #e74c3c; color: #c0392b; padding: 15px; border-radius: 10px; text-align: center; font-weight: bold; margin-bottom: 20px; max-width: 700px; margin-left: auto; margin-right: auto; }}
            .ok-banner {{ background: #e0f9e6; border: 2px solid #27ae60; color: #1e8449; padding: 15px; border-radius: 10px; text-align: center; font-weight: bold; margin-bottom: 20px; max-width: 700px; margin-left: auto; margin-right: auto; }}
            .summary-box {{ display: flex; justify-content: center; gap: 20px; flex-wrap: wrap; margin-bottom: 30px; }}
            .summary-item {{ background: white; padding: 8px 14px; border-radius: 20px; font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
            .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
            .month-block {{ background: white; border-radius: 12px; padding: 20px; margin: 0 auto 30px auto; max-width: 900px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
            .weekday-row {{ display: grid; grid-template-columns: repeat(7, 1fr); margin-bottom: 6px; }}
            .weekday {{ text-align: center; font-weight: bold; color: #666; font-size: 13px; }}
            .calendar-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }}
            .day {{ border: 1px solid #eee; border-radius: 6px; padding: 4px; min-height: 70px; font-size: 11px; }}
            .day.overlap {{ border: 3px solid #e74c3c; box-shadow: 0 0 6px rgba(231,76,60,0.5); }}
            .overlap-badge {{ background: #e74c3c; color: white; font-size: 9px; padding: 1px 4px; border-radius: 4px; text-align: center; margin-bottom: 2px; font-weight: bold; }}
            .empty {{ min-height: 70px; }}
            .date-num {{ font-weight: bold; font-size: 13px; margin-bottom: 3px; }}
            .platform {{ border-radius: 4px; padding: 2px 4px; margin-bottom: 2px; font-size: 10px; }}
        </style>
    </head>
    <body>
        <h1>🏡 세모집_제주 예약 현황</h1>
        <div class="updated">생성 시각: {datetime.now(ZoneInfo("Asia/Seoul")).isoformat()[:16].replace("T", " ")} 기준, 앞으로 {DAYS_TO_SHOW}일</div>
        {warning_banner}
        {summary_box}
        {month_blocks}
    </body>
    </html>
    """
    return html


def main():
    print("네이버 예약 현황 확인 중...")
    naver_status = get_naver_status()

    print("에어비앤비 예약 현황 확인 중...")
    airbnb_status = get_airbnb_status()

    print("HTML 대시보드 생성 중...")
    html = build_html(naver_status, airbnb_status)

    output_path = os.path.join(os.getcwd(), "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"완료! 파일 위치: {output_path}")


if __name__ == "__main__":
    main()
