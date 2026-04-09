from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.urls import reverse_lazy

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url=reverse_lazy('login'), permanent=False)),
    path('', include('parrainage.urls')),
]
