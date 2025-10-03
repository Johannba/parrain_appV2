from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0007_referral_uniq_referee_per_company'),  # remplace par la dernière migration existante
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],  # pas d'action en base
            state_operations=[
                migrations.AddConstraint(
                    model_name='referral',
                    constraint=models.UniqueConstraint(
                        fields=['referee', 'company'],
                        name='uniq_referee_per_company',
                    ),
                ),
            ],
        ),
    ]
