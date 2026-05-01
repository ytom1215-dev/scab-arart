import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, date
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 日本語フォント対応のエラーハンドリング
try:
    import japanize_matplotlib
except ImportError:
    pass

# ============================================================
# 設定・定数
# ============================================================
LOCATIONS = {
    "西之表市（種子島）": (30.73, 131.00),
    "長島町":            (32.18, 130.12),
    "鹿屋市（大隅）":    (31.38, 130.85),
    "南さつま市":        (31.41, 130.32),
    "伊仙町（徳之島）":  (27.68, 128.93),
    "知名町（沖永良部）":(27.38, 128.59),
}

st.set_page_config(page_title="そうか病かん水アラート", layout="wide")

# ============================================================
# 気象データ取得関数 (実績 + 予報)
# ============================================================
@st.cache_data(ttl=3600)
def fetch_combined_weather(lat, lon, planting_date):
    today = date.today()
    # 1. 実績データの取得 (植え付け日から昨日まで)
    start_str = planting_date.strftime('%Y-%m-%d')
    end_past_str = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    
    url_past = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&daily=temperature_2m_mean,precipitation_sum&timezone=Asia%2FTokyo&start_date={start_str}&end_date={end_past_str}"
    url_fcast = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_mean,precipitation_sum&timezone=Asia%2FTokyo"
    
    try:
        res_p = requests.get(url_past).json()
        res_f = requests.get(url_fcast).json()
        
        df_p = pd.DataFrame(res_p['daily'])
        df_f = pd.DataFrame(res_f['daily'])
        
        df = pd.concat([df_p, df_f]).drop_duplicates('time').sort_values('time')
        df['time'] = pd.to_datetime(df['time']).dt.date
        df['is_forecast'] = df['time'] >= today
        return df
    except Exception as e:
        st.error(f"気象データの取得に失敗しました。期間が早すぎるかAPIエラーです: {e}")
        return None

# ============================================================
# メイン UI
# ============================================================
st.title("🥔 そうか病「水かけサイン」アラート")
st.markdown("最も重要な「塊茎形成期」の乾燥リスクを、明日からの予報を含めて判定します。")

# サイドバー設定
with st.sidebar:
    st.header("📍 圃場設定")
    loc_name = st.selectbox("地点選択", list(LOCATIONS.keys()))
    lat, lon = LOCATIONS[loc_name]
    planting_date = st.date_input("植え付け日", date.today() - timedelta(days=45))
    
    st.divider()
    st.header("⏱️ リスク期間の推定方法")
    risk_method = st.radio(
        "推定方法を選択",
        ["植え付け後日数で指定", "積算温度(GDD)で推定"]
    )

    if risk_method == "積算温度(GDD)で推定":
        gdd_start = st.number_input("開始 GDD", value=300)
        gdd_end = st.number_input("終了 GDD", value=600)
        base_temp = 7.0
    else:
        day_start = st.number_input("開始日数 (植え付け後)", value=40)
        day_end = st.number_input("終了日数 (植え付け後)", value=70)

    st.divider()
    st.header("💧 かん水目標")
    target_precip = st.number_input("目標降水量 (mm)", value=80)
    danger_precip = st.number_input("警戒降水量 (mm)", value=30)

# 実行処理
if planting_date > date.today():
    st.warning("植え付け日が未来です。今日以前の日付を選択してください。")
else:
    df = fetch_combined_weather(lat, lon, planting_date)
    
    if df is not None:
        # GDD計算（グラフ表示用には常に計算）
        df['gdd_val'] = (df['temperature_2m_mean'] - 7.0).clip(lower=0)
        df['cum_gdd'] = df['gdd_val'].cumsum()
        
        # --- リスク期間の特定ロジック ---
        if risk_method == "積算温度(GDD)で推定":
            risk_start_row = df[df['cum_gdd'] >= gdd_start].head(1)
            risk_end_row = df[df['cum_gdd'] >= gdd_end].head(1)
            
            if risk_start_row.empty:
                r_start_date = None
            else:
                r_start_date = risk_start_row['time'].values[0]
                r_end_date = risk_end_row['time'].values[0] if not risk_end_row.empty else df['time'].max()
        else:
            # 日数指定モード
            r_start_date = planting_date + timedelta(days=day_start)
            r_end_date = planting_date + timedelta(days=day_end)
            
            # データ範囲外のチェック
            if r_start_date > df['time'].max():
                r_start_date = None

        today = date.today()
        
        if r_start_date is None:
            st.info(f"🌱 現在、生育中。リスク期（{'積算温度' if risk_method.startswith('積算') else '指定日数'}）にまだ達していません。")
        else:
            # リスク期間内の降水量集集計
            # 予報期間を超えている場合は取得できている最大日まで
            r_end_actual = min(r_end_date, df['time'].max())
            
            risk_period_df = df[(df['time'] >= r_start_date) & (df['time'] <= r_end_actual)]
            actual_precip = risk_period_df[risk_period_df['is_forecast'] == False]['precipitation_sum'].sum()
            forecast_precip = risk_period_df[risk_period_df['is_forecast'] == True]['precipitation_sum'].sum()
            total_precip_est = actual_precip + forecast_precip
            
            # --- 表示セクション ---
            st.subheader(f"📅 判定期間: {r_start_date.strftime('%m/%d')} ～ {r_end_date.strftime('%m/%d')}")
            if r_end_date > df['time'].max():
                st.caption(f"※{df['time'].max().strftime('%m/%d')} 以降の予報データがまだないため、現時点での予測値です。")

            col1, col2, col3 = st.columns(3)
            col1.metric("今日までの実績降雨", f"{actual_precip:.1f} mm")
            col2.metric("今後の予報降雨", f"{forecast_precip:.1f} mm")
            col3.metric("合計推定（実績+予報）", f"{total_precip_est:.1f} mm")

            # --- アラート表示 ---
            st.divider()
            if total_precip_est < danger_precip:
                st.error(f"### ⚠️ 警告：乾燥リスク【高】\n予測降水量が {danger_precip}mm を下回っています。早急にかん水を検討してください。")
                st.markdown(f"💡 **アドバイス:** 目標の{target_precip}mmまで、あと **{max(0.0, target_precip - total_precip_est):.1f}mm** 不足しています。")
            elif total_precip_est < target_precip:
                st.warning(f"### ⚠ 注意：乾燥リスク【中】\n目標の {target_precip}mm に届かない予測です。土壌の乾き具合を見てかん水してください。")
                st.markdown(f"💡 **アドバイス:** あと **{max(0.0, target_precip - total_precip_est):.1f}mm** のかん水を推奨します。")
            else:
                st.success(f"### ✅ 安心：水分は十分な見込みです\n現在の予報では十分な水分が確保される予定です。")

            # --- グラフ表示 ---
            fig, ax = plt.subplots(figsize=(10, 4))
            fig.patch.set_facecolor("#0e1117")
            ax.set_facecolor("#1a1d24")
            
            # 降水量バー
            colors = ['#4fc3f7' if not f else '#ffeb3b' for f in df['is_forecast']]
            ax.bar(df['time'], df['precipitation_sum'].fillna(0), color=colors, label="降水量 (青:実績 / 黄:予報)")
            
            # リスク期間の強調
            ax.axvspan(r_start_date, r_end_date, color='red', alpha=0.1, label="感染リスク期")
            ax.axvline(today, color='white', linestyle='--', alpha=0.8, label="今日")
            
            ax.set_ylabel("日降水量 (mm)", color="white")
            ax.tick_params(colors="white")
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            plt.xticks(rotation=45, color="white")
            plt.yticks(color="white")
            plt.legend(loc='upper left', fontsize='small')
            st.pyplot(fig)

            # 詳細データ
            with st.expander("詳細な予報データ（リスク期間中）"):
                st.dataframe(risk_period_df[['time', 'temperature_2m_mean', 'precipitation_sum', 'is_forecast']].rename(columns={
                    'time': '日付', 'temperature_2m_mean': '平均気温', 'precipitation_sum': '予測降水量(mm)', 'is_forecast': '予報か？'
                }))

st.divider()
st.caption("※本アプリはOpen-Meteoの気象データを使用しています。実際の土壌水分はマルチの有無や土質によって異なります。")