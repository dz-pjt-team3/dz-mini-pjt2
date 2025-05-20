import os
import re
import requests
import markdown
from flask import Flask, render_template, request, redirect, url_for
from openai import OpenAI
from dotenv import load_dotenv

# 환경변수(.env)에서 API 키 로드
load_dotenv()
app = Flask(__name__)

# OpenAI 클라이언트 생성
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# GPT에 여행 일정 생성 요청을 보내고, 마크다운 형식 텍스트 반환
def generate_itinerary(prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 전문 여행 일정 플래너입니다."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"에러 발생: {e}"

# 일정 텍스트에서 "",''로 묶인 장소명 추출
def extract_places(text: str) -> list:
    pattern = r"['‘“\"](.+?)['’”\"]"
    matches = re.findall(pattern, text)
    return list(set(matches))

# HTML에서 장소명에 <span> 태그 추가
def linkify_places(html: str, place_names: list) -> str:
    for place in place_names:
        html = html.replace(
            place,
            f'<span class="place-link" data-name=\"{place}\">{place}</span>'
        )
    return html

# 장소명 → 위도/경도 변환
def get_kakao_coords(place_name: str):
    KEY = os.environ["KAKAO_REST_API_KEY"]
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KEY}"}
    params = {"query": place_name}

    res = requests.get(url, headers=headers, params=params).json()
    if res.get('documents'):
        lat = res['documents'][0]['y']
        lng = res['documents'][0]['x']
        return lat, lng
    return None

# GPT 응답 텍스트 → 일정 리스트 추출
def extract_schedule_entries(text: str) -> list:
    pattern = r"(\d+일차)(?:\s*[:\-]?\s*)?(.*?)(?=\d+일차|$)"
    entries = re.findall(pattern, text, re.DOTALL)
    schedule = []
    for day, body in entries:
        for line in body.strip().split("\n"):
            time_match = re.match(r"(\d{1,2}:\d{2})", line)
            time = time_match.group(1) if time_match else ""
            place_match = re.search(r"[\"“‘'](.+?)[\"”’']", line)
            if place_match:
                place = place_match.group(1)
                desc = line.replace(place_match.group(0), "").strip(" :-~")
                schedule.append({
                    "day": day,
                    "time": time,
                    "place": place,
                    "desc": desc
                })
    return schedule

# 카테고리 코드별 검색 (관광지, 음식점 등)
def search_category(category_code: str, region: str, size=15, radius=1000) -> list:
    REST_KEY = os.environ["KAKAO_REST_API_KEY"]
    coords = get_kakao_coords(region)  # region을 좌표로 변환
    if not coords:
        return []
    lat, lng = coords
    
    url = "https://dapi.kakao.com/v2/local/search/category.json"
    headers = {"Authorization": f"KakaoAK {REST_KEY}"}
    params = {
        "category_group_code": category_code,
        "x": lng,           # 경도
        "y": lat,           # 위도
        "radius": radius,   # 반경 (m)
        "size": size
    }
    res = requests.get(url, headers=headers, params=params).json()
    return res.get("documents", [])

# ✅ 메인페이지: 히어로 섹션만 렌더링
@app.route("/")
def index():
    return render_template("index.html")

# ✅ 음식점 페이지
@app.route("/food", methods=["GET", "POST"])
def food():
    places = []
    youtube_videos = []
    center_lat = 37.5665
    center_lng = 126.9780

    if request.method == "POST":
        region = request.form.get("region")

        # ✅ 1. Kakao API 음식점 검색
        REST_KEY = os.environ["KAKAO_REST_API_KEY"]
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        headers = {"Authorization": f"KakaoAK {REST_KEY}"}
        params = {"query": f"{region} 맛집", "size": 10}

        try:
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            places = [
                {
                    "name": doc["place_name"],
                    "address": doc["road_address_name"],
                    "lat": doc["y"],
                    "lng": doc["x"]
                }
                for doc in data["documents"]
            ]

            if places:
                center_lat = float(places[0]["lat"])
                center_lng = float(places[0]["lng"])
        except Exception as e:
            places = [{"name": f"에러 발생: {e}", "address": ""}]

        # ✅ 2. YouTube API 영상 검색 (GPT 제거)
        youtube_videos = search_youtube_videos(f"{region} 맛집")

    return render_template("food.html",
                           places=places,
                           youtube_videos=youtube_videos,
                           kakao_key=os.environ["KAKAO_JAVASCRIPT_KEY"],
                           center_lat=center_lat,
                           center_lng=center_lng)



# ✅ 카페 페이지
@app.route("/cafe", methods=["GET", "POST"])
def cafe():
    places = []
    youtube_videos = []
    center_lat = 37.5665  # 기본 중심 (서울)
    center_lng = 126.9780

    if request.method == "POST":
        region = request.form.get("region")

        # ✅ Kakao API로 카페 검색
        REST_KEY = os.environ["KAKAO_REST_API_KEY"]
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        headers = {"Authorization": f"KakaoAK {REST_KEY}"}
        params = {"query": f"{region} 카페", "size": 10}

        try:
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            places = [
                {
                    "name": doc["place_name"],
                    "address": doc["road_address_name"],
                    "lat": doc["y"],
                    "lng": doc["x"]
                }
                for doc in data["documents"]
            ]

            if places:
                center_lat = float(places[0]["lat"])
                center_lng = float(places[0]["lng"])

        except Exception as e:
            places = [{"name": f"에러 발생: {e}", "address": ""}]

        # ✅ 유튜브 추천
        youtube_videos = search_youtube_videos(f"{region} 카페")

    return render_template("cafe.html",
                           places=places,
                           youtube_videos=youtube_videos,
                           kakao_key=os.environ["KAKAO_JAVASCRIPT_KEY"],
                           center_lat=center_lat,
                           center_lng=center_lng)


# ✅ 숙소 페이지
@app.route("/acc", methods=["GET", "POST"])
def acc():
    places = []
    youtube_videos = []
    center_lat = 37.5665  # 기본 중심 (서울)
    center_lng = 126.9780

    if request.method == "POST":
        region = request.form.get("region")

        # ✅ Kakao API로 숙소 검색
        REST_KEY = os.environ["KAKAO_REST_API_KEY"]
        url = "https://dapi.kakao.com/v2/local/search/keyword.json"
        headers = {"Authorization": f"KakaoAK {REST_KEY}"}
        params = {"query": f"{region} 숙소", "size": 10}

        try:
            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()

            places = [
                {
                    "name": doc["place_name"],
                    "address": doc["road_address_name"],
                    "lat": doc["y"],
                    "lng": doc["x"]
                }
                for doc in data["documents"]
            ]

            if places:
                center_lat = float(places[0]["lat"])
                center_lng = float(places[0]["lng"])

        except Exception as e:
            places = [{"name": f"에러 발생: {e}", "address": ""}]

        # ✅ 유튜브 숙소 추천
        youtube_videos = search_youtube_videos(f"{region} 숙소")

    return render_template("acc.html",
                           places=places,
                           youtube_videos=youtube_videos,
                           kakao_key=os.environ["KAKAO_JAVASCRIPT_KEY"],
                           center_lat=center_lat,
                           center_lng=center_lng)


# ✅ 일정 생성 및 지도 표시
@app.route("/plan", methods=["GET", "POST"])
def plan():
    result = ""
    markers = []
    center_lat, center_lng = 36.5, 127.5  # 기본 지도 중심

    if request.method == "POST":
        # 사용자 입력
        start_date     = request.form.get("start_date")
        end_date       = request.form.get("end_date")
        companions     = request.form.get("companions")
        people_count   = request.form.get("people_count")
        theme          = request.form.getlist("theme")
        theme_str      = ", ".join(theme)
        user_prompt    = request.form.get("user_prompt")
        location       = request.form.get("location")
        transport_mode = request.form.get("transport_mode")

        coords = get_kakao_coords(location)
        if coords:
            center_lat, center_lng = coords

        code_map = {
            "restaurant": "FD6",  # 음식점
            "cafe":       "CE7",  # 카페
            "tourism":    "AT4",  # 관광지
        }
        all_places = []
        for code in code_map.values():
            docs = search_category(code, location, size=20, radius=1000)
            all_places += [d["place_name"] for d in docs]
        unique_places = list(dict.fromkeys(all_places))[:10]
        places_str = ", ".join(unique_places)

        place_videos = {}
        for place in unique_places:
            vids = search_youtube_videos(f"{place} 여행", max_results=3)
            place_videos[place] = [v["title"] for v in vids]

        yt_info_str = "\n".join(
            f"- {p}: " + (", ".join(ts) if ts else "관련 영상 없음")
            for p, ts in place_videos.items()
        )

        prompt = f"""
        여행 날짜: {start_date} ~ {end_date}
        동행: {companions}, 총 인원: {people_count}명
        여행지: {location}, 테마: {theme_str}
        교통수단: {transport_mode}
        추가 조건: {user_prompt}

        # 장소별 YouTube 참고 영상 제목:
        {yt_info_str}

        **출력 형식**
        1일차:\n
        1) "장소명"\n
        • 한줄 설명.\n
        • 영업시간 :\n
        • 입장료 or 메뉴추천:\n

        **출력조건**
        - {location}에 따른 장소는 2~ 3곳으로 고정.
        - 여행일정 장소명 앞에 {location} 추가.
        - 위 “유튜브 참고 영상”을 참고하여, 각 장소에 대한 추가 설명(추천 이유, 꿀팁 등)을 일정에 반영해주세요.
        - 각 일정에 따라 정해진 장소들 끼리 거리가 멀지않은곳으로 추천해주세요.
        - 교통수단에 따라 일정을 조율해주세요.
        - 가게(음식점, 카페)나 관광지같은경우 영업시간, 입장료, 메뉴추천 등등 정보를 적어주세요.
        - 시간 앞에 적힌 장소명은 반드시 큰따옴표(\"\")로 묶어주세요.
        """

        raw_result = generate_itinerary(prompt)
        result = markdown.markdown(raw_result)
        place_names = extract_places(raw_result)
        result = linkify_places(result, place_names)

        schedule_data = extract_schedule_entries(raw_result)
        for entry in schedule_data:
            coord = get_kakao_coords(entry["place"])
            if coord:
                markers.append({
                    "name": entry["place"],
                    "lat": coord[0],
                    "lng": coord[1],
                    "day": entry["day"],
                    "time": entry["time"],
                    "desc": entry["desc"]
                })

    return render_template("plan.html",
                           result=result,
                           kakao_key=os.environ["KAKAO_JAVASCRIPT_KEY"],
                           markers=markers,
                           center_lat=center_lat,
                           center_lng=center_lng)

# ✅ 카테고리 검색 (음식점, 카페, 관광지 등)
@app.route("/search/<category>")
def search(category):
    code_map = {"cafe":"CE7", "restaurant":"FD6", "tourism":"AT4"}
    code = code_map.get(category)
    if not code:
        return redirect(url_for("index"))

    region = request.args.get("region", "")
    places = search_category(code, region)

    return render_template(
        "search.html",
        category=category,
        region=region,
        places=places
    )

def search_youtube_videos(query, max_results=5):
    api_key = os.environ["YOUTUBE_API_KEY"]
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": api_key
    }

    res = requests.get(url, params=params)
    videos = []

    if res.status_code == 200:
        data = res.json()
        for item in data["items"]:
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            thumbnail = item["snippet"]["thumbnails"]["medium"]["url"]
            videos.append({
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": thumbnail
            })
    return videos


if __name__ == "__main__":
    app.run(debug=True)
