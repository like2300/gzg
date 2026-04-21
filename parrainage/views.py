from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, FileResponse, Http404
from django.core.paginator import Paginator
from decimal import Decimal
from functools import wraps
import os
from .models import Profile, Payment, GlobalSettings, PDFDocument, AppLink


def is_admin(user):
    """Test si l'utilisateur est un administrateur (staff et superuser)"""
    return user.is_authenticated and user.is_staff and user.is_superuser


def admin_required(view_func):
    """Décorateur personnalisé pour restreindre l'accès aux admins"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not (request.user.is_staff and request.user.is_superuser):
            messages.error(request, 'Accès refusé. Cette page est réservée aux administrateurs.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def login_view(request):
    """Page de connexion"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Nom d\'utilisateur ou mot de passe incorrect.')
    
    return render(request, 'parrainage/login.html')


def logout_view(request):
    """Déconnexion"""
    logout(request)
    return redirect('login')


def register_view(request):
    """
    Page d'inscription avec système de parrainage OBLIGATOIRE
    Le code de parrain est récupéré depuis l'URL (?ref=CODE)
    SANS parrain, l'inscription est BLOQUÉE
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    ref_code = request.GET.get('ref', '')
    referrer_profile = None
    referral_limit_reached = False

    # === BLOCAGE : Pas de code de parrain = accès interdit ===
    if not ref_code:
        messages.error(request, '⛔ L\'inscription sans parrain est interdise. Vous devez avoir un code de parrainage pour vous inscrire.')
        return redirect('login')

    # Vérifier le code de parrain
    try:
        referrer_profile = Profile.objects.get(referral_code=ref_code)
        # Vérifier si le parrain a atteint la limite
        if not referrer_profile.can_refer:
            referral_limit_reached = True
            messages.error(request, '⛔ Ce parrain a atteint le nombre maximum de filleuls (2). Inscription impossible avec ce code.')
            return redirect('login')
    except Profile.DoesNotExist:
        messages.error(request, '⛔ Code de parrainage invalide. Inscription impossible.')
        return redirect('login')

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        referrer_code = request.POST.get('referrer_code', '')

        # === BLOCAGE : Vérifier que le code de parrain est toujours valide ===
        if not referrer_code:
            messages.error(request, '⛔ Le code de parrainage est obligatoire.')
            return render(request, 'parrainage/register.html', {
                'referrer_code': ref_code,
                'referrer_profile': referrer_profile,
                'referral_limit_reached': False
            })

        # Vérifier que le parrain existe et peut encore parrainer
        try:
            referrer = Profile.objects.get(referral_code=referrer_code)
            if not referrer.can_refer:
                messages.error(request, '⛔ Ce parrain a atteint le nombre maximum de filleuls. Inscription impossible.')
                return redirect('login')
        except Profile.DoesNotExist:
            messages.error(request, '⛔ Code de parrainage invalide. Inscription impossible.')
            return redirect('login')

        # Validation
        if not username or not email or not password:
            messages.error(request, 'Tous les champs sont obligatoires.')
        elif password != confirm_password:
            messages.error(request, 'Les mots de passe ne correspondent pas.')
        elif len(password) < 8:
            messages.error(request, 'Le mot de passe doit contenir au moins 8 caractères.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Ce nom d\'utilisateur existe déjà.')
        else:
            with transaction.atomic():
                # Créer l'utilisateur
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password
                )

                # Créer le profil avec le parrain OBLIGATOIRE
                profile = Profile.objects.create(
                    user=user,
                    referrer=referrer
                )

                # Connecter l'utilisateur
                login(request, user)
                messages.success(request, f'✅ Bienvenue {username} ! Votre compte a été créé avec succès. Votre parrain est {referrer.user.username}.')
                return redirect('download_app')

    return render(request, 'parrainage/register.html', {
        'referrer_code': ref_code,
        'referrer_profile': referrer_profile,
        'referral_limit_reached': referral_limit_reached
    })


@login_required
@admin_required
def update_referral_limit_view(request):
    """
    API pour mettre à jour la limite de parrainage globale
    """
    if request.method == 'POST':
        try:
            new_limit = int(request.POST.get('limit', 2))
            if new_limit < 1:
                return JsonResponse({
                    'success': False,
                    'error': 'La limite doit être au moins 1'
                })

            settings, _ = GlobalSettings.objects.get_or_create(id=1)
            old_limit = settings.referral_limit
            settings.referral_limit = new_limit
            settings.save(update_fields=['referral_limit'])

            return JsonResponse({
                'success': True,
                'message': f'Limite de parrainage mise à jour: {old_limit} → {new_limit}',
                'new_limit': new_limit
            })
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Valeur invalide'
            })

    return JsonResponse({
        'success': False,
        'error': 'Méthode non autorisée'
    })


@login_required
def download_app_view(request):
    """
    Page de téléchargement de l'application
    - Si mobile: affiche la page avec le lien de téléchargement
    - Si PC: redirige directement vers le dashboard
    """
    # Vérifier si l'utilisateur est sur mobile
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    is_mobile = bool(
        'mobile' in user_agent or
        'android' in user_agent or
        'iphone' in user_agent or
        'ipad' in user_agent or
        'ipod' in user_agent
    )

    # Si c'est un PC, redirection directe vers le dashboard
    if not is_mobile:
        return redirect('dashboard')

    # Récupérer le lien Play Store
    app_link = AppLink.objects.first()
    play_store_url = app_link.play_store_url if app_link else "https://play.google.com/store/apps"

    context = {
        'play_store_url': play_store_url,
    }

    return render(request, 'parrainage/download_app.html', context)


@login_required
def dashboard_view(request):
    """
    Tableau de bord utilisateur avec:
    - Progression vers le statut VIP
    - Lien de parrainage et QR Code
    - Historique des paiements
    - Liste des filleuls
    """
    profile, created = Profile.objects.get_or_create(user=request.user)
    quota = GlobalSettings.get_current_quota()
    payments = profile.payments.all()[:10]  # 10 derniers paiements
    referrals = profile.referrals.all()[:10]  # 10 premiers filleuls

    # Récupérer les documents PDF disponibles (tous les documents actifs pour tout le monde)
    pdf_documents = PDFDocument.objects.filter(is_active=True)

    # Calculer le stroke-dashoffset pour la progression circulaire
    # Circonférence = 2 * π * r = 2 * 3.14 * 70 ≈ 440
    # stroke-dashoffset = 440 - (440 * progress_percent / 100)
    progress_percent = profile.progress_percent
    stroke_dashoffset = max(0, 440 - (440 * progress_percent / 100))

    context = {
        'profile': profile,
        'quota': quota,
        'payments': payments,
        'referrals': referrals,
        'stroke_dashoffset': stroke_dashoffset,
        'is_profile_complete': profile.is_profile_complete,
        'pdf_documents': pdf_documents,
    }

    return render(request, 'parrainage/dashboard.html', context)


@login_required
def my_referrals_view(request):
    """
    Page pour voir tous ses filleuls avec leurs détails
    """
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    # Récupérer tous les filleuls directs
    referrals = profile.referrals.all().order_by('-user__date_joined')
    
    # Récupérer l'arbre complet des filleuls
    downline_tree = profile.get_downline_tree()
    
    # Calculer les statistiques
    total_referrals = referrals.count()
    vip_referrals = referrals.filter(is_vip=True).count()
    total_earned = sum(r.total_paid for r in referrals)
    
    # Compter tous les filleuls en profondeur
    def count_all_downline(tree):
        count = 0
        for node in tree:
            count += 1
            count += count_all_downline(node['children'])
        return count
    
    total_downline = count_all_downline(downline_tree)
    
    context = {
        'profile': profile,
        'referrals': referrals,
        'total_referrals': total_referrals,
        'vip_referrals': vip_referrals,
        'total_earned': total_earned,
        'downline_tree': downline_tree,
        'total_downline': total_downline,
    }
    
    return render(request, 'parrainage/my_referrals.html', context)


@login_required
def profile_view(request):
    """
    Page de profil utilisateur avec QR code et lien de parrainage
    """
    from django_countries import countries as countries_data
    
    profile, created = Profile.objects.get_or_create(user=request.user)
    quota = GlobalSettings.get_current_quota()

    # Compter le réseau total
    def count_downline(tree):
        count = 0
        for node in tree:
            count += 1
            count += count_downline(node.get('children', []))
        return count

    total_downline = count_downline(profile.get_downline_tree())

    # Gestion de la modification du profil
    if request.method == 'POST' and 'update_profile' in request.POST:
        username = request.POST.get('username')
        email = request.POST.get('email')
        phone_number = request.POST.get('phone_number')
        country = request.POST.get('country')

        if username and email:
            # Vérifier si le nom d'utilisateur existe déjà (pour un autre utilisateur)
            if User.objects.filter(username=username).exclude(pk=request.user.pk).exists():
                messages.error(request, 'Ce nom d\'utilisateur est déjà pris.')
            else:
                request.user.username = username
                request.user.email = email
                request.user.save()
                
                # Mettre à jour le profil
                profile.phone_number = phone_number
                profile.country = country
                profile.save()
                
                messages.success(request, 'Profil mis à jour avec succès !')
                return redirect('profile')

    context = {
        'profile': profile,
        'quota': quota,
        'total_downline': total_downline,
        'countries': list(countries_data),
    }

    return render(request, 'parrainage/profile.html', context)


@login_required
def make_payment_view(request):
    """
    Page pour effectuer un paiement
    """
    profile, created = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        amount = request.POST.get('amount')
        reference = request.POST.get('reference')

        if not amount or not reference:
            messages.error(request, 'Tous les champs sont obligatoires.')
        else:
            try:
                amount_decimal = Decimal(amount)
                if amount_decimal <= 0:
                    raise ValueError("Le montant doit être positif")

                with transaction.atomic():
                    Payment.objects.create(
                        profile=profile,
                        amount=amount_decimal,
                        reference=reference
                    )

                messages.success(request, f'Paiement de {amount_decimal} FCFA enregistré avec succès!')
                return redirect('dashboard')
            except ValueError as e:
                messages.error(request, f'Montant invalide: {str(e)}')
            except Exception as e:
                messages.error(request, f'Erreur lors du paiement: {str(e)}')

    return render(request, 'parrainage/payment.html', {'profile': profile})


@login_required
def view_parrain_tree(request, pk):
    """
    Vue pour afficher l'arbre de parrainage d'un parrain spécifique
    Redirige vers l'interface n8n
    """
    return network_tree_visual_view(request, pk)


@login_required
def view_child_detail(request, pk):
    """
    Vue détaillée pour un enfant spécifique dans l'arbre
    Affiche ses informations et tous ses descendants
    """
    child_profile = get_object_or_404(Profile, pk=pk)
    my_profile, created = Profile.objects.get_or_create(user=request.user)

    # Récupérer les filleuls directs
    referrals = child_profile.referrals.all().order_by('-user__date_joined')

    # Récupérer l'arbre complet
    downline_tree = child_profile.get_downline_tree(max_depth=100)

    # Statistiques
    total_referrals = referrals.count()
    vip_referrals = referrals.filter(is_vip=True).count()
    remaining_referrals = child_profile.REFERRAL_LIMIT - total_referrals

    def count_all_downline(tree):
        count = 0
        for node in tree:
            count += 1
            count += count_all_downline(node['children'])
        return count

    total_downline = count_all_downline(downline_tree)

    # Fil d'ariane
    breadcrumbs = []
    current = child_profile
    while current:
        breadcrumbs.append(current)
        current = current.referrer
    breadcrumbs.reverse()

    context = {
        'current_profile': child_profile,
        'my_profile': my_profile,
        'profile': child_profile,
        'referrals': referrals,
        'total_referrals': total_referrals,
        'vip_referrals': vip_referrals,
        'remaining_referrals': remaining_referrals,
        'downline_tree': downline_tree,
        'total_downline': total_downline,
        'breadcrumbs': breadcrumbs,
    }

    return render(request, 'parrainage/child_detail.html', context)


@login_required
def network_tree_visual_view(request, pk=None):
    """
    Vue style n8n - Arbre de parrainage visuel et interactif
    Interface épurée avec noeuds connectés
    """
    import json
    from django.core.serializers.json import DjangoJSONEncoder
    
    if pk:
        root_profile = get_object_or_404(Profile, pk=pk)
    else:
        root_profile, created = Profile.objects.get_or_create(user=request.user)
    
    my_profile, created = Profile.objects.get_or_create(user=request.user)
    
    # Récupérer l'arbre complet
    downline_tree = root_profile.get_downline_tree(max_depth=100)
    
    # Convertir l'arbre en JSON
    def build_node_data(node):
        return {
            'id': node['profile'].pk,
            'username': node['profile'].user.username,
            'referral_code': node['profile'].referral_code,
            'is_vip': node['profile'].is_vip,
            'total_paid': float(node['profile'].total_paid),
            'progress_percent': node['profile'].progress_percent,
            'referrals_count': node['profile'].referrals.count(),
            'level': node['level'],
            'date_joined': node['profile'].user.date_joined.strftime('%d/%m/%Y'),
            'children': [build_node_data(child) for child in node.get('children', [])]
        }
    
    # Construire la racine
    root_data = {
        'id': root_profile.pk,
        'username': root_profile.user.username,
        'referral_code': root_profile.referral_code,
        'is_vip': root_profile.is_vip,
        'total_paid': float(root_profile.total_paid),
        'progress_percent': root_profile.progress_percent,
        'referrals_count': root_profile.referrals.count(),
        'level': 0,
        'date_joined': root_profile.user.date_joined.strftime('%d/%m/%Y'),
        'children': [build_node_data(child) for child in downline_tree]
    }
    
    tree_json = json.dumps(root_data, cls=DjangoJSONEncoder)
    
    # Fil d'ariane
    breadcrumbs = []
    current = root_profile
    while current:
        breadcrumbs.append(current)
        current = current.referrer
    breadcrumbs.reverse()

    # Récupérer les enfants directs pour l'affichage
    children = []
    for node in downline_tree:
        child_data = {
            'profile': node['profile'],
            'children': node.get('children', [])
        }
        children.append(child_data)

    context = {
        'root_profile': root_profile,
        'my_profile': my_profile,
        'tree_json': tree_json,
        'breadcrumbs': breadcrumbs,
        'children': children,
        'total_downline': sum(1 for _ in root_profile.get_downline_tree(level=0, max_depth=100)),
    }

    return render(request, 'parrainage/network_tree.html', context)


@login_required
def network_tree_api(request, pk=None):
    """
    API JSON pour l'arbre de parrainage
    Retourne les données pour l'interface visuelle
    """
    if pk:
        root_profile = get_object_or_404(Profile, pk=pk)
    else:
        root_profile, created = Profile.objects.get_or_create(user=request.user)
    
    def build_node(profile, level=0):
        """Construit un noeud JSON pour l'arbre"""
        node = {
            'id': profile.pk,
            'username': profile.user.username,
            'referral_code': profile.referral_code,
            'is_vip': profile.is_vip,
            'total_paid': float(profile.total_paid),
            'progress_percent': profile.progress_percent,
            'referrals_count': profile.referrals.count(),
            'level': level,
            'date_joined': profile.user.date_joined.strftime('%d/%m/%Y'),
            'children': []
        }
        
        for referral in profile.referrals.all():
            node['children'].append(build_node(referral, level + 1))
        
        return node
    
    tree_data = build_node(root_profile)

    return JsonResponse(tree_data)


# ============================================
# ADMIN DASHBOARD
# ============================================

@admin_required
def admin_dashboard_view(request):
    """
    Dashboard d'administration moderne et épuré
    Vue d'ensemble des utilisateurs, paiements et statistiques
    """
    # Statistiques globales
    total_users = User.objects.count()
    total_vip = Profile.objects.filter(is_vip=True).count()
    total_non_vip = total_users - total_vip
    total_payments = Payment.objects.aggregate(total=Sum('amount'))['total'] or 0
    total_payments_count = Payment.objects.count()
    
    # Quota global
    quota = GlobalSettings.get_current_quota()
    
    # Utilisateurs par statut
    vip_percentage = (total_vip / total_users * 100) if total_users > 0 else 0
    
    # Derniers paiements
    recent_payments = Payment.objects.select_related('profile__user').order_by('-date_created')[:10]
    
    # Top contributeurs
    top_contributors = Profile.objects.select_related('user').order_by('-total_paid')[:10]
    
    # Derniers inscrits
    recent_users = Profile.objects.select_related('user').order_by('-user__date_joined')[:10]
    
    # Répartition par progression
    progress_0_25 = Profile.objects.filter(total_paid=0).count()
    progress_25_50 = Profile.objects.filter(total_paid__gt=0, total_paid__lt=float(quota)*0.5).count()
    progress_50_75 = Profile.objects.filter(total_paid__gte=float(quota)*0.5, total_paid__lt=float(quota)*0.75).count()
    progress_75_100 = Profile.objects.filter(total_paid__gte=float(quota)*0.75, is_vip=False).count()
    
    # Calculs pour le template
    quota_float = float(quota)
    quota_half = quota_float / 2
    quota_75 = quota_float * 0.75
    
    context = {
        'total_users': total_users,
        'total_vip': total_vip,
        'total_non_vip': total_non_vip,
        'vip_percentage': vip_percentage,
        'total_payments': total_payments,
        'total_payments_count': total_payments_count,
        'recent_payments': recent_payments,
        'top_contributors': top_contributors,
        'recent_users': recent_users,
        'quota': quota,
        'quota_half': quota_half,
        'quota_75': quota_75,
        'progress_0_25': progress_0_25,
        'progress_25_50': progress_25_50,
        'progress_50_75': progress_50_75,
        'progress_75_100': progress_75_100,
    }
    
    return render(request, 'parrainage/admin/dashboard.html', context)


@admin_required
def admin_users_view(request):
    """
    Liste de tous les utilisateurs avec filtres et pagination
    """
    # Récupérer tous les profils
    profiles = Profile.objects.select_related('user', 'referrer').all().order_by('-user__date_joined')
    
    # Filtres
    search = request.GET.get('search', '')
    status = request.GET.get('status', '')
    
    if search:
        profiles = profiles.filter(
            Q(user__username__icontains=search) |
            Q(user__email__icontains=search) |
            Q(referral_code__icontains=search)
        )
    
    if status == 'vip':
        profiles = profiles.filter(is_vip=True)
    elif status == 'non_vip':
        profiles = profiles.filter(is_vip=False)
    
    # Pagination
    paginator = Paginator(profiles, 25)
    page = request.GET.get('page', 1)
    profiles_page = paginator.get_page(page)
    
    # Statistiques
    total_users = profiles.count()
    vip_count = profiles.filter(is_vip=True).count()
    quota = GlobalSettings.get_current_quota()
    referral_limit = GlobalSettings.get_referral_limit()

    context = {
        'profiles': profiles_page,
        'total_users': total_users,
        'vip_count': vip_count,
        'search': search,
        'status': status,
        'quota': quota,
        'referral_limit': referral_limit,
    }

    return render(request, 'parrainage/admin/users.html', context)


@admin_required
def admin_user_detail_view(request, pk):
    """
    Détail complet d'un utilisateur avec tous ses paiements
    """
    profile = get_object_or_404(Profile.objects.select_related('user', 'referrer'), pk=pk)
    quota = GlobalSettings.get_current_quota()

    # Génération de lien de réinitialisation
    if request.method == 'POST' and 'generate_reset_link' in request.POST:
        duration = int(request.POST.get('duration', 24))  # heures
        from django.utils.crypto import get_random_string
        from datetime import timedelta
        from django.utils import timezone

        token = get_random_string(32)
        expires_at = timezone.now() + timedelta(hours=duration)

        # Stocker le token
        profile.reset_token = token
        profile.reset_token_expires = expires_at
        profile.save(update_fields=['reset_token', 'reset_token_expires'])

        # Créer le lien
        reset_link = request.build_absolute_uri(
            f'/reset-password/{profile.user.username}/{token}/'
        )

        # Message de succès avec le lien
        messages.success(
            request,
            f'<strong>Lien généré pour {profile.user.username}</strong><br>'
            f'Valable {duration}h<br>'
            f'<div class="mt-2 p-2 bg-white/10 rounded text-xs break-all font-mono">'
            f'{reset_link}</div>'
            f'<button onclick="navigator.clipboard.writeText(\'{reset_link}\')" '
            f'class="mt-1 px-3 py-1 bg-white/20 hover:bg-white/30 rounded text-xs transition-colors">'
            f'<i class="bi bi-clipboard"></i> Copier le lien</button>'
        )

        # Continuer vers l'affichage des détails avec le lien
        payments = Payment.objects.filter(profile=profile).order_by('-date_created')
        direct_referrals = profile.referrals.all()
        downline_tree = profile.get_downline_tree(max_depth=100)
        
        def count_all_downline(tree):
            count = 0
            for node in tree:
                count += 1
                count += count_all_downline(node.get('children', []))
            return count

        total_downline = count_all_downline(downline_tree)
        quota = GlobalSettings.get_current_quota()

        context = {
            'profile': profile,
            'quota': quota,
            'payments': payments,
            'direct_referrals': direct_referrals,
            'downline_tree': downline_tree,
            'total_downline': total_downline,
            'total_payments_sum': sum(p.amount for p in payments),
            'reset_link': reset_link,
            'reset_duration': duration,
        }

        return render(request, 'parrainage/admin/user_detail.html', context)

    # Tous les paiements de l'utilisateur
    payments = Payment.objects.filter(profile=profile).order_by('-date_created')

    # Ses filleuls directs
    direct_referrals = profile.referrals.all()

    # Arbre complet
    downline_tree = profile.get_downline_tree(max_depth=100)

    # Compter tous les descendants
    def count_all_downline(tree):
        count = 0
        for node in tree:
            count += 1
            count += count_all_downline(node.get('children', []))
        return count

    total_downline = count_all_downline(downline_tree)

    # Récupérer le lien de réinitialisation s'il existe
    reset_link = None
    if profile.reset_token and profile.reset_token_expires:
        from django.utils import timezone
        if profile.reset_token_expires > timezone.now():
            reset_link = request.build_absolute_uri(
                f'/reset-password/{profile.user.username}/{profile.reset_token}/'
            )

    context = {
        'profile': profile,
        'quota': quota,
        'payments': payments,
        'direct_referrals': direct_referrals,
        'downline_tree': downline_tree,
        'total_downline': total_downline,
        'total_payments_sum': sum(p.amount for p in payments),
        'reset_link': reset_link,
    }

    return render(request, 'parrainage/admin/user_detail.html', context)


@admin_required
def admin_payments_view(request):
    """
    Liste de tous les paiements avec filtres
    """
    payments = Payment.objects.select_related('profile__user').order_by('-date_created')

    # Filtres
    search = request.GET.get('search', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if search:
        payments = payments.filter(
            Q(profile__user__username__icontains=search) |
            Q(reference__icontains=search)
        )

    if start_date:
        payments = payments.filter(date_created__gte=start_date)

    if end_date:
        payments = payments.filter(date_created__lte=end_date)

    # Pagination
    paginator = Paginator(payments, 25)
    page = request.GET.get('page', 1)
    payments_page = paginator.get_page(page)

    # Statistiques
    total_amount = payments.aggregate(total=Sum('amount'))['total'] or 0

    context = {
        'payments': payments_page,
        'total_amount': total_amount,
        'search': search,
        'start_date': start_date,
        'end_date': end_date,
    }

    return render(request, 'parrainage/admin/payments.html', context)


@admin_required
def admin_new_payment_view(request):
    """
    Page pour créer un nouveau paiement (admin)
    """
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        amount = request.POST.get('amount')
        reference = request.POST.get('reference')

        if not user_id or not amount or not reference:
            messages.error(request, 'Tous les champs sont obligatoires.')
        else:
            try:
                user = User.objects.get(pk=user_id)
                profile = Profile.objects.get(user=user)
                amount_decimal = Decimal(amount)

                if amount_decimal <= 0:
                    raise ValueError("Le montant doit être positif")

                with transaction.atomic():
                    Payment.objects.create(
                        profile=profile,
                        amount=amount_decimal,
                        reference=reference
                    )

                messages.success(request, f'Paiement de {amount_decimal} FCFA enregistré avec succès!')
                return redirect('admin_payments')
            except User.DoesNotExist:
                messages.error(request, 'Utilisateur non trouvé.')
            except Profile.DoesNotExist:
                messages.error(request, 'Profil non trouvé.')
            except ValueError as e:
                messages.error(request, f'Montant invalide: {str(e)}')
            except Exception as e:
                messages.error(request, f'Erreur lors du paiement: {str(e)}')

    # Récupérer tous les utilisateurs pour le select
    users = User.objects.all().order_by('username')

    return render(request, 'parrainage/admin/new_payment.html', {'users': users})


@login_required
def reset_password_view(request, username, token):
    """
    Page de réinitialisation de mot de passe via lien unique
    """
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    
    User = get_user_model()
    
    try:
        user = User.objects.get(username=username)
        profile = Profile.objects.get(user=user)
    except (User.DoesNotExist, Profile.DoesNotExist):
        messages.error(request, 'Lien invalide ou expiré.')
        return redirect('login')
    
    # Vérifier le token et son expiration
    if not profile.reset_token or profile.reset_token != token:
        messages.error(request, 'Lien invalide ou expiré.')
        return redirect('login')
    
    if profile.reset_token_expires and profile.reset_token_expires < timezone.now():
        messages.error(request, 'Lien expiré. Veuillez en demander un nouveau.')
        profile.reset_token = None
        profile.reset_token_expires = None
        profile.save(update_fields=['reset_token', 'reset_token_expires'])
        return redirect('login')
    
    # Traitement du formulaire
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if new_password != confirm_password:
            messages.error(request, 'Les mots de passe ne correspondent pas.')
        elif len(new_password) < 8:
            messages.error(request, 'Le mot de passe doit contenir au moins 8 caractères.')
        else:
            user.set_password(new_password)
            user.save()
            
            # Invalider le token
            profile.reset_token = None
            profile.reset_token_expires = None
            profile.save(update_fields=['reset_token', 'reset_token_expires'])
            
            messages.success(request, 'Mot de passe modifié avec succès !')
            return redirect('login')
    
    context = {
        'username': username,
    }
    
    return render(request, 'parrainage/reset_password.html', context)



@admin_required
def admin_network_tree_view(request, pk=None):
    """
    Vue admin pour voir TOUS les réseaux avec hiérarchie complète
    Permet de naviguer dans n'importe quel arbre de parrainage
    """
    import json
    from django.core.serializers.json import DjangoJSONEncoder

    if pk:
        root_profile = get_object_or_404(Profile, pk=pk)
    else:
        # Par défaut, montrer le premier utilisateur ou rediriger vers la liste
        root_profile = Profile.objects.first()
        if not root_profile:
            messages.warning(request, 'Aucun utilisateur dans le système.')
            return redirect('admin_users')

    # Récupérer l'arbre complet avec profondeur maximale
    downline_tree = root_profile.get_downline_tree(max_depth=100)

    # Compter tous les descendants
    def count_all_downline(tree):
        count = 0
        for node in tree:
            count += 1
            count += count_all_downline(node.get('children', []))
        return count

    total_downline = count_all_downline(downline_tree)

    # Fil d'ariane
    breadcrumbs = []
    current = root_profile
    while current:
        breadcrumbs.append(current)
        current = current.referrer
    breadcrumbs.reverse()

    # Récupérer les enfants directs pour l'affichage
    children = []
    for node in downline_tree:
        child_data = {
            'profile': node['profile'],
            'children': node.get('children', [])
        }
        children.append(child_data)

    # Tous les utilisateurs pour le selecteur
    all_users = Profile.objects.select_related('user').all().order_by('user__username')

    context = {
        'root_profile': root_profile,
        'tree_json': json.dumps({'id': root_profile.pk, 'username': root_profile.user.username}, cls=DjangoJSONEncoder),
        'breadcrumbs': breadcrumbs,
        'children': children,
        'total_downline': total_downline,
        'all_users': all_users,
        'admin_mode': True,
    }

    return render(request, 'parrainage/admin/admin_network_tree.html', context)


@admin_required
def admin_all_networks_view(request):
    """
    Vue admin pour voir la liste de TOUS les réseaux
    """
    # Récupérer tous les profils avec leurs statistiques
    profiles = Profile.objects.select_related('user').prefetch_related('referrals').all().order_by('-user__date_joined')

    # Filtres
    search = request.GET.get('search', '')
    status = request.GET.get('status', '')

    if search:
        profiles = profiles.filter(
            Q(user__username__icontains=search) |
            Q(user__email__icontains=search) |
            Q(referral_code__icontains=search) |
            Q(matricule__icontains=search)
        )

    if status == 'vip':
        profiles = profiles.filter(is_vip=True)
    elif status == 'non_vip':
        profiles = profiles.filter(is_vip=False)

    # Pagination
    paginator = Paginator(profiles, 25)
    page = request.GET.get('page', 1)
    profiles_page = paginator.get_page(page)

    # Statistiques globales
    total_networks = profiles.count()
    vip_count = profiles.filter(is_vip=True).count()

    context = {
        'profiles': profiles_page,
        'total_networks': total_networks,
        'vip_count': vip_count,
        'search': search,
        'status': status,
    }

    return render(request, 'parrainage/admin/admin_all_networks.html', context)


@admin_required
def admin_settings_view(request):
    """
    Page des paramètres de l'application
    Permet de modifier le quota global requis pour devenir VIP
    et de configurer le préfixe du matricule
    """
    config, _ = GlobalSettings.objects.get_or_create(id=1)
    quota = config.required_quota

    # Statistiques pour le template
    total_users = User.objects.count()
    total_vip = Profile.objects.filter(is_vip=True).count()
    total_non_vip = total_users - total_vip
    
    # Prochain matricule à être généré
    next_matricule = f"{config.matricule_prefix}{config.matricule_counter}"

    if request.method == 'POST':
        # Mise à jour du quota
        new_quota = request.POST.get('required_quota')
        if new_quota:
            try:
                new_quota_decimal = Decimal(new_quota)
                if new_quota_decimal <= 0:
                    raise ValueError("Le montant doit être supérieur à zéro")
                
                # Compter combien d'utilisateurs non-VIP deviendront VIP
                anciens_vip_count = Profile.objects.filter(is_vip=True).count()
                futurs_vip_count = Profile.objects.filter(
                    is_vip=False,
                    total_paid__gte=new_quota_decimal
                ).count()

                config.required_quota = new_quota_decimal
                config.save()  # Le save() appellera le recalcul automatiquement
                
                if futurs_vip_count > 0:
                    messages.success(request, 
                        f'✅ Quota mis à jour ! {futurs_vip_count} utilisateur(s) deviennent automatiquement VIP.')
                else:
                    messages.success(request, 
                        f'Quota mis à jour avec succès ! Nouveau montant : {new_quota_decimal} FCFA')
            except ValueError as e:
                messages.error(request, f'Montant invalide : {str(e)}')
        
        # Mise à jour du préfixe de matricule
        new_prefix = request.POST.get('matricule_prefix')
        if new_prefix:
            new_prefix_upper = new_prefix.strip().upper()
            if len(new_prefix_upper) >= 2 and new_prefix_upper.isalnum():
                old_prefix = config.matricule_prefix
                config.matricule_prefix = new_prefix_upper
                messages.success(request, f'Préfixe de matricule mis à jour : {old_prefix} → {new_prefix_upper}')
            else:
                messages.error(request, 'Le préfixe doit contenir au moins 2 caractères alphanumériques.')
        
        # Mise à jour du compteur de matricule
        new_counter = request.POST.get('matricule_counter')
        if new_counter:
            try:
                new_counter_int = int(new_counter)
                if new_counter_int < 0:
                    raise ValueError("Le compteur doit être positif")
                
                old_counter = config.matricule_counter
                config.matricule_counter = new_counter_int
                messages.success(request, f'Compteur de matricule mis à jour : {old_counter} → {new_counter_int}')
            except ValueError as e:
                messages.error(request, f'Compteur invalide : {str(e)}')
        
        config.save()
        return redirect('admin_settings')

    context = {
        'quota': quota,
        'total_users': total_users,
        'total_vip': total_vip,
        'total_non_vip': total_non_vip,
        'matricule_prefix': config.matricule_prefix,
        'matricule_counter': config.matricule_counter,
        'next_matricule': next_matricule,
    }

    return render(request, 'parrainage/admin/admin_settings.html', context)


@login_required
def download_pdf(request, pk):
    """Télécharger un document PDF"""
    pdf_document = get_object_or_404(PDFDocument, pk=pk, is_active=True)

    # Vérifier que le fichier existe
    if not pdf_document.file:
        raise Http404("Fichier non disponible")

    # Ouvrir et servir le fichier
    try:
        response = FileResponse(
            pdf_document.file.open('rb'),
            content_type='application/pdf'
        )
        response['Content-Disposition'] = f'attachment; filename="{pdf_document.title}.pdf"'
        return response
    except Exception as e:
        raise Http404(f"Erreur lors du téléchargement: {str(e)}")


def service_worker(request):
    """Servir le fichier service-worker.js pour la PWA"""
    from django.conf import settings
    from django.http import HttpResponse
    import os

    sw_path = os.path.join(settings.STATIC_ROOT, 'parrainage', 'js', 'service-worker.js')
    
    try:
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        response = HttpResponse(content, content_type='text/javascript')
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    except FileNotFoundError:
        raise Http404("Service worker not found")


def csrf_failure(request, reason=""):
    """Vue personnalisée pour les erreurs CSRF (403)"""
    return render(request, 'parrainage/errors/403_csrf.html', {'reason': reason}, status=403)


def error_403_view(request, exception=None):
    """Vue générique pour les erreurs 403"""
    return render(request, 'parrainage/errors/403.html', status=403)


def error_404_view(request, exception=None):
    """Vue pour les erreurs 404 - Page non trouvée"""
    return render(request, 'parrainage/errors/404.html', status=404)


def error_500_view(request):
    """Vue pour les erreurs 500 - Erreur serveur"""
    return render(request, 'parrainage/errors/500.html', status=500)
