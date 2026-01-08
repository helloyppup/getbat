# utils/styles.py
import streamlit as st

def apply_global_styles():
    """应用全局 CSS 样式"""
    st.markdown("""
    <style>
        .main-header {font-size: 2.5rem; color: #4F8BF9; font-weight: 700;}
        .sub-header {font-size: 1.5rem; color: #333; margin-top: 20px;}
        .stButton>button {width: 100%; border-radius: 5px; height: 3em; font-weight: bold;}
        .metric-card {background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 15px; border-radius: 8px;}
    </style>
    """, unsafe_allow_html=True)

def setup_page():
    """页面基础配置"""
    st.set_page_config(
        page_title="Dognoise 压测自助平台",
        page_icon="🐕",
        layout="wide",
        initial_sidebar_state="expanded"
    )