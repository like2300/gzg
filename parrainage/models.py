from django.db import models
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.conf import settings
import urllib.parse
from django_countries.fields import CountryField


# --- CONFIGURATION GLOBALE DU QUOTA ---
class GlobalSettings(models.Model):
    """
    Table unique pour définir le montant que TOUT LE MONDE doit atteindre.
    Exemple : 100 000 FCFA.
    """
    required_quota = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=100000.00,
        help_text="Le montant total pour devenir VIP et accéder aux marchés."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Paramètre Global"
        verbose_name_plural = "Paramètres Globaux"

    def save(self, *args, **kwargs):
        # Sécurité pour n'avoir qu'une seule ligne de configuration
        if not self.pk and GlobalSettings.objects.exists():
            raise ValidationError("Il ne peut y avoir qu'une seule configuration globale.")
        return super().save(*args, **kwargs)

    @classmethod
    def get_current_quota(cls):
        config, _ = cls.objects.get_or_create(id=1)
        return config.required_quota


# --- PROFIL UTILISATEUR & RÉSEAU ---
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    # Parrainage Binaire (Auto-référencement)
    referrer = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals'
    )

    # Code de parrainage basé sur le username (ex: OMER-FILS)
    referral_code = models.CharField(max_length=50, unique=True, editable=False)

    # Informations de contact
    phone_number = models.CharField(max_length=20, blank=True, null=True, help_text="Numéro de téléphone")
    country = CountryField(blank=True, null=True, help_text="Pays de résidence")

    # Finance
    total_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_vip = models.BooleanField(default=False)

    # Token de réinitialisation de mot de passe
    reset_token = models.CharField(max_length=64, blank=True, null=True)
    reset_token_expires = models.DateTimeField(blank=True, null=True)

    # Limite de parrainage
    REFERRAL_LIMIT = 2  # Maximum 2 filleuls directs

    def __str__(self):
        return f"Profil de {self.user.username} ({self.referral_code})"

    @property
    def is_profile_complete(self):
        """Vérifie si le profil est complet (téléphone et pays remplis)"""
        return bool(self.phone_number and self.country)

    # --- ALGORITHME D'UNICITÉ DU CODE ---
    def generate_unique_code(self):
        """Génère un code propre et unique basé sur le nom d'utilisateur"""
        base = slugify(self.user.username).upper()
        if not base:
            base = "PARTENAIRE"
        
        code = base
        counter = 1
        # Boucle tant que le code existe déjà pour un autre profil
        while Profile.objects.filter(referral_code=code).exclude(pk=self.pk).exists():
            code = f"{base}-{counter}"
            counter += 1
        return code

    # --- CALCULS DYNAMIQUES ---
    @property
    def remaining_amount(self):
        """Soustraction automatique : Quota Global - Déjà payé"""
        from decimal import Decimal
        quota = GlobalSettings.get_current_quota()
        return max(Decimal(quota) - Decimal(self.total_paid), Decimal(0))

    @property
    def progress_percent(self):
        """Pourcentage pour le cercle de progression (Dashboard)"""
        from decimal import Decimal
        quota = GlobalSettings.get_current_quota()
        if quota <= 0: return 0
        return min((float(self.total_paid) / float(quota)) * 100, 100)

    # --- URLS DYNAMIQUES & QR CODE ---
    @property
    def referral_link(self):
        """Génère l'URL de parrainage selon le domaine actuel du serveur"""
        try:
            current_site = Site.objects.get_current().domain
            # On détecte le protocole selon le mode (Debug ou Prod)
            protocol = 'http' if settings.DEBUG else 'https'
        except:
            current_site = "localhost:8000"
            protocol = "http"
        
        return f"{protocol}://{current_site}/register/?ref={self.referral_code}"

    @property
    def qr_code_url(self):
        """Génère l'URL de l'API externe pour le QR Code"""
        encoded_link = urllib.parse.quote(self.referral_link)
        return f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_link}"

    # --- SAUVEGARDE ET VALIDATION ---
    def save(self, *args, **kwargs):
        # 1. Générer le code unique si absent
        if not self.referral_code:
            self.referral_code = self.generate_unique_code()
        
        # 2. Vérifier le statut VIP
        if self.total_paid >= GlobalSettings.get_current_quota():
            self.is_vip = True
            
        super().save(*args, **kwargs)
    
    # --- LIMITES DE PARRAINAGE ---
    @property
    def can_refer(self):
        """Vérifie si l'utilisateur peut encore parrainer"""
        return self.referrals.count() < self.REFERRAL_LIMIT
    
    @property
    def referrals_count(self):
        """Nombre de filleuls directs"""
        return self.referrals.count()
    
    @property
    def remaining_referrals(self):
        """Nombre de filleuls restants à parrainer"""
        return max(self.REFERRAL_LIMIT - self.referrals.count(), 0)
    
    def get_downline_tree(self, level=0, max_depth=10):
        """
        Récupère l'arbre complet des filleuls (récursif)
        Retourne une liste de dicts avec profil et enfants
        """
        if level >= max_depth:
            return []
        
        tree = []
        for referral in self.referrals.all():
            node = {
                'profile': referral,
                'level': level + 1,
                'children': referral.get_downline_tree(level + 1, max_depth)
            }
            tree.append(node)
        return tree


# --- HISTORIQUE DES PAIEMENTS ---
class Payment(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True, help_text="ID Transaction Mobile Money")
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_created']
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"

    def __str__(self):
        return f"Paiement de {self.amount} FCFA par {self.profile.user.username}"

    def save(self, *args, **kwargs):
        # On enregistre le paiement
        super().save(*args, **kwargs)
        # On met à jour le total cumulé du profil
        self.profile.total_paid += self.amount
        self.profile.save()


# --- DOCUMENTS PDF ---
class PDFDocument(models.Model):
    """
    Documents PDF téléchargeables accessibles depuis le dashboard
    """
    title = models.CharField(max_length=200, help_text="Titre du document")
    description = models.TextField(blank=True, help_text="Description courte du document")
    file = models.FileField(upload_to='documents/pdfs/', help_text="Fichier PDF à télécharger")
    is_active = models.BooleanField(default=True, help_text="Document visible par les utilisateurs")
    require_vip = models.BooleanField(default=False, help_text="Réservé aux utilisateurs VIP uniquement")
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_created']
        verbose_name = "Document PDF"
        verbose_name_plural = "Documents PDF"

    def __str__(self):
        return self.title

    @property
    def file_size(self):
        """Retourne la taille du fichier en Ko"""
        if self.file:
            return round(self.file.size / 1024, 2)
        return 0

    @property
    def file_url(self):
        """Retourne l'URL du fichier"""
        if self.file:
            return self.file.url
        return ''
