from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('mes-filleuls/', views.my_referrals_view, name='my_referrals'),
    path('profil/', views.profile_view, name='profile'),
    path('payment/', views.make_payment_view, name='make_payment'),
    
    # Navigation infinie dans l'arbre de parrainage (Poupées Russes)
    path('parrain/<int:pk>/', views.view_parrain_tree, name='view_parrain_tree'),
    path('enfant/<int:pk>/', views.view_child_detail, name='view_child_detail'),
    
    # Interface style n8n - Arbre visuel (URLs principales)
    path('network/', views.network_tree_visual_view, name='network_tree'),
    path('network/<int:pk>/', views.network_tree_visual_view, name='network_tree_pk'),
    path('api/network/', views.network_tree_api, name='network_tree_api'),
    path('api/network/<int:pk>/', views.network_tree_api, name='network_tree_api_pk'),
    
    # Administration
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('admin-users/', views.admin_users_view, name='admin_users'),
    path('admin-users/<int:pk>/', views.admin_user_detail_view, name='admin_user_detail'),
    path('admin-payments/', views.admin_payments_view, name='admin_payments'),
    path('admin-payments/new/', views.admin_new_payment_view, name='admin_new_payment'),
    
    # Réinitialisation de mot de passe
    path('reset-password/<str:username>/<str:token>/', views.reset_password_view, name='reset_password'),

    # Admin Network Trees - Vue complète de tous les réseaux
    path('admin-networks/', views.admin_all_networks_view, name='admin_all_networks'),
    path('admin-network/<int:pk>/', views.admin_network_tree_view, name='admin_network_tree'),
    
    # Paramètres de l'application
    path('admin-settings/', views.admin_settings_view, name='admin_settings'),
]
