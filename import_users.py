import os
import django
import zipfile
import xml.etree.ElementTree as ET

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

# Now imports that depend on django settings
from django.utils.text import slugify
from django.contrib.auth.models import User
from django.db import transaction
from parrainage.models import Profile, GlobalSettings

def get_docx_rows(path):
    document = zipfile.ZipFile(path)
    xml_content = document.read('word/document.xml')
    document.close()
    tree = ET.fromstring(xml_content)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    rows = []
    for table in tree.findall('.//w:tbl', ns):
        for row in table.findall('.//w:tr', ns):
            cells = []
            for cell in row.findall('.//w:tc', ns):
                text = "".join([t.text for t in cell.findall('.//w:t', ns) if t.text])
                cells.append(text.strip())
            rows.append(cells)
    return rows

def create_users():
    rows = get_docx_rows('../LE RESEAU DU GZ global.docx')
    if not rows:
        print("No rows found.")
        return

    # Skip header
    data_rows = rows[1:]
    
    # Map for linking: doc_matricule -> Profile object
    # We use this to establish relationships as defined in the doc
    doc_matricule_to_profile = {}
    
    # Clean up matricules for mapping
    def clean_m(m):
        if not m: return ""
        return m.replace('–', '-').replace(' ', '').strip()

    print(f"Starting import of {len(data_rows)} entries with app-generated matricules...")

    with transaction.atomic():
        for i, row in enumerate(data_rows):
            if not row or len(row) < 2:
                continue
            
            full_name = row[0]
            doc_matricule = row[1]
            
            if not full_name:
                continue

            # 1. Generate unique username
            base_username = slugify(full_name)
            if not base_username:
                base_username = "user"
            
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}-{counter:03d}"
                counter += 1
            
            # 2. Create User
            user = User.objects.create_user(
                username=username,
                password='password123',
                email=f"{username}@gz-reseau.com"
            )
            
            # 3. Create Profile
            # IMPORTANT: We DO NOT set matricule here. 
            # Profile.save() will call GlobalSettings.generate_next_matricule()
            profile = Profile.objects.create(
                user=user
            )
            
            # Save mapping using the DOCUMENT matricule as key
            cleaned_doc_m = clean_m(doc_matricule)
            doc_matricule_to_profile[cleaned_doc_m] = profile
            
            if i % 50 == 0:
                print(f"Created {i} users... Last: {username} (New matricule: {profile.matricule})")

        # 4. Set Referrers using the mapping
        print("Linking referrers using document mapping...")
        links_count = 0
        for i, row in enumerate(data_rows):
            if not row or len(row) < 4:
                continue
            
            doc_self_m = clean_m(row[1])
            doc_sponsor_m = clean_m(row[3])
            
            if not doc_sponsor_m or doc_sponsor_m.startswith('---'):
                continue
            
            profile = doc_matricule_to_profile.get(doc_self_m)
            sponsor_profile = doc_matricule_to_profile.get(doc_sponsor_m)
            
            if profile and sponsor_profile:
                profile.referrer = sponsor_profile
                profile.save()
                links_count += 1
            
        print(f"Linking completed: {links_count} relations established.")

    print("Import completed successfully.")

if __name__ == "__main__":
    create_users()
