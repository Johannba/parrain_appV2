from django.core.management.base import BaseCommand, CommandError
from accounts.models import Company
from rewards.services.probabilities import ensure_wheels

class Command(BaseCommand):
    help = "Initialise les roues de probabilité pour une entreprise."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Slug de l'entreprise")

    def handle(self, *args, **options):
        slug = options["company"]
        try:
            company = Company.objects.get(slug=slug)
        except Company.DoesNotExist:
            raise CommandError(f"Company '{slug}' introuvable")

        ensure_wheels(company)
        self.stdout.write(self.style.SUCCESS(f"OK: {company} • base & very_rare"))
