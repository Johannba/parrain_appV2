# rewards/urls.py
from django.urls import path
from .views import (
    reward_list, reward_update, rewards_history_company, reward_spin,
    use_reward, distribute_reward, referral_delete,rewards_stats,test_wheel, reward_send_sms
)

app_name = "rewards"

urlpatterns = [
    path("", reward_list, name="list"),
    path("<int:pk>/edit/", reward_update, name="edit"),
    path("<int:pk>/update/", reward_update, name="update"), 
    path("history/", rewards_history_company, name="history_company"),
    path("stats/", rewards_stats, name="stats"),  
    path("spin/<int:reward_id>/", reward_spin, name="spin"),
    path("use/<str:token>/", use_reward, name="use_reward"),
    path("distribute/<int:pk>/", distribute_reward, name="distribute"),
    path("referral/<int:pk>/delete/", referral_delete, name="referral_delete"),
    path("test-wheel/", test_wheel, name="test_wheel"), 
    path("<int:pk>/send/sms/", reward_send_sms, name="reward_send_sms"),
    
]
