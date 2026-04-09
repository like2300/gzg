from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.urls import reverse_lazy
from parrainage.views import error_403_view, error_404_view, error_500_view

# Gestionnaires d'erreurs personnalisés
handler403 = error_403_view
handler404 = error_404_view
handler500 = error_500_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url=reverse_lazy('login'), permanent=False)),
    path('', include('parrainage.urls')),
]
