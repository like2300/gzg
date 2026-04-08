from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django import forms
from django.urls import path
from django.http import JsonResponse
from django.db.models import Q
from unfold.admin import ModelAdmin
from .models import GlobalSettings, Profile, Payment


class PaymentAdminForm(forms.ModelForm):
    """Custom form with user selector widget"""

    user_search = forms.CharField(
        label='Rechercher un utilisateur',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'vTextField',
            'placeholder': 'Tapez pour rechercher (nom, email, code...)',
            'id': 'user-search-input',
            'autocomplete': 'off',
        })
    )

    class Meta:
        model = Payment
        fields = '__all__'
        widgets = {
            'profile': forms.Select(attrs={
                'id': 'id_profile_select',
                'class': 'admin-autocomplete',
            }),
            'amount': forms.NumberInput(attrs={'class': 'vIntegerField'}),
            'reference': forms.TextInput(attrs={'class': 'vTextField'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make profile field optional initially, will be set via JS
        self.fields['profile'].required = False
        self.fields['profile'].widget.attrs['readonly'] = 'readonly'
        self.fields['profile'].widget.attrs['placeholder'] = 'Sélectionnez un utilisateur d\'abord'


# Déregistrer le Site par défaut pour le réenregistrer avec unfold si nécessaire
# admin.site.unregister(Site)


@admin.register(GlobalSettings)
class GlobalSettingsAdmin(ModelAdmin):
    list_display = ['required_quota', 'updated_at']
    readonly_fields = ['updated_at']
    
    fieldsets = (
        ("Configuration du Quota", {
            "fields": ("required_quota",),
            "description": "Définissez le montant requis pour devenir VIP"
        }),
        ("Informations", {
            "fields": ("updated_at",),
            "classes": ("collapse",)
        }),
    )
    
    def has_add_permission(self, request):
        # Empêcher l'ajout de multiples configurations
        return not GlobalSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ['user', 'referral_code', 'referrer', 'total_paid', 'is_vip', 'progress_percent_display']
    list_filter = ['is_vip', 'user__date_joined']
    search_fields = ['user__username', 'user__email', 'referral_code']
    readonly_fields = ['referral_code', 'is_vip', 'referral_link_display', 'qr_code_display', 'progress_bar']
    
    fieldsets = (
        ("Informations Utilisateur", {
            "fields": ("user", "referrer")
        }),
        ("Parrainage", {
            "fields": ("referral_code", "referral_link_display", "qr_code_display"),
            "description": "Code et lien de parrainage uniques"
        }),
        ("Progression Financière", {
            "fields": ("total_paid", "progress_bar", "is_vip"),
            "description": "Suivi des paiements et statut VIP"
        }),
    )
    
    def progress_percent_display(self, obj):
        return f"{obj.progress_percent:.1f}%"
    progress_percent_display.short_description = "Progression"
    
    def referral_link_display(self, obj):
        return obj.referral_link
    referral_link_display.short_description = "Lien de Parrainage"
    
    def qr_code_display(self, obj):
        from django.utils.html import format_html
        return format_html('<img src="{}" alt="QR Code" style="max-width:200px;" />', obj.qr_code_url)
    qr_code_display.short_description = "QR Code"
    
    def progress_bar(self, obj):
        from django.utils.html import format_html
        percent = obj.progress_percent
        color = "green" if percent >= 100 else "orange" if percent >= 50 else "red"
        return format_html(
            '''
            <div style="width:100%;background:#e0e0e0;border-radius:10px;overflow:hidden;">
                <div style="width:{}%;background:{};height:20px;border-radius:10px;transition:width 0.3s;"></div>
            </div>
            <p style="text-align:center;margin-top:5px;">{:.1f}% complété</p>
            ''',
            percent, color, percent
        )
    progress_bar.short_description = "Barre de Progression"


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    form = PaymentAdminForm
    list_display = ['profile', 'amount', 'reference', 'date_created']
    list_filter = ['date_created']
    search_fields = ['profile__user__username', 'reference']
    readonly_fields = ['date_created']

    fieldsets = (
        ("Recherche d'Utilisateur", {
            "fields": ("user_search",),
            "description": "Tapez au moins 2 caractères pour rechercher un utilisateur"
        }),
        ("Détails du Paiement", {
            "fields": ("profile", "amount", "reference")
        }),
        ("Date", {
            "fields": ("date_created",),
            "classes": ("collapse",)
        }),
    )

    class Media:
        js = ('parrainage/js/payment-user-search.js',)
        css = {
            'all': ('parrainage/css/payment-user-search.css',)
        }

    def get_urls(self):
        """Add custom URL for user search API"""
        urls = super().get_urls()
        custom_urls = [
            path(
                'search-user/',
                self.admin_site.admin_view(self.search_user),
                name='parrainage_payment_search_user',
            ),
        ]
        return custom_urls + urls

    def search_user(self, request):
        """AJAX endpoint to search users"""
        query = request.GET.get('q', '')
        if len(query) < 2:
            return JsonResponse({'results': []})

        users = User.objects.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        ).select_related('profile')[:10]

        results = []
        for user in users:
            profile = getattr(user, 'profile', None)
            referral_code = profile.referral_code if profile else 'N/A'
            results.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'referral_code': referral_code,
                'display': f"{user.username} ({user.email}) - Code: {referral_code}"
            })

        return JsonResponse({'results': results})
