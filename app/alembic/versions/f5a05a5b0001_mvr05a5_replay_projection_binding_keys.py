"""MVR-05A5: bind replay projections and their replacement identities.

The pre-MVR-05 runtime has exactly one provable compatibility binding.  This
revision attributes only absent/legacy rows to that binding.  A partially
converted database carrying any other binding is ambiguous at this boundary:
the transaction raises before DDL or row mutation, leaving those rows isolated
on the old schema for explicit repair instead of guessing or copying them.
"""

from alembic import op


revision = "f5a05a5b0001"
down_revision = "f4a05a4b0001"
branch_labels = None
depends_on = None
reversibility = "forward-only"

_COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"


def upgrade() -> None:
    op.execute(
        rf"""
        DO $mvr05a5$
        DECLARE
          replay_table text;
          unexpected_binding text;
        BEGIN
          LOCK TABLE public.standing_questions, public.episodes,
                     public.episode_engine_state, public.episode_artifact_binding,
                     public.decisions, public.decision_outcomes
            IN SHARE ROW EXCLUSIVE MODE;

          -- A foreign binding on an unstamped/partial schema is not attributable
          -- by this migration.  Refuse before the first ALTER/UPDATE so the
          -- transaction keeps every source row intact for explicit repair.
          FOREACH replay_table IN ARRAY ARRAY[
            'standing_questions','episodes','episode_engine_state',
            'episode_artifact_binding','decisions','decision_outcomes'
          ] LOOP
            -- decisions already carries an explicit MVR-05A3 binding column;
            -- a non-compatibility value there is provenance, not ambiguity.
            IF replay_table <> 'decisions' AND EXISTS (
              SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name=replay_table
                 AND column_name='vault_binding_id'
            ) THEN
              EXECUTE format(
                'SELECT min(vault_binding_id) FROM public.%I '
                'WHERE vault_binding_id IS NOT NULL AND vault_binding_id <> %L',
                replay_table, '{_COMPATIBILITY_BINDING_ID}'
              ) INTO unexpected_binding;
              IF unexpected_binding IS NOT NULL THEN
                RAISE EXCEPTION USING
                  MESSAGE=format('MVR-05A5 ambiguous replay binding in %I', replay_table),
                  HINT='Keep mixed-mode startup blocked; repair the source attribution and rerun.';
              END IF;
            END IF;
          END LOOP;

          ALTER TABLE public.standing_questions ADD COLUMN IF NOT EXISTS vault_binding_id text;
          ALTER TABLE public.episodes ADD COLUMN IF NOT EXISTS vault_binding_id text;
          ALTER TABLE public.episode_engine_state ADD COLUMN IF NOT EXISTS vault_binding_id text;
          ALTER TABLE public.episode_artifact_binding ADD COLUMN IF NOT EXISTS vault_binding_id text;
          ALTER TABLE public.decisions ADD COLUMN IF NOT EXISTS vault_binding_id text;
          ALTER TABLE public.decision_outcomes ADD COLUMN IF NOT EXISTS vault_binding_id text;

          UPDATE public.standing_questions SET vault_binding_id='{_COMPATIBILITY_BINDING_ID}'
            WHERE vault_binding_id IS NULL;
          UPDATE public.episodes SET vault_binding_id='{_COMPATIBILITY_BINDING_ID}'
            WHERE vault_binding_id IS NULL;
          UPDATE public.episode_engine_state SET vault_binding_id='{_COMPATIBILITY_BINDING_ID}'
            WHERE vault_binding_id IS NULL;
          UPDATE public.episode_artifact_binding SET vault_binding_id='{_COMPATIBILITY_BINDING_ID}'
            WHERE vault_binding_id IS NULL;
          UPDATE public.decisions SET vault_binding_id='{_COMPATIBILITY_BINDING_ID}'
            WHERE vault_binding_id IS NULL;
          UPDATE public.decision_outcomes SET vault_binding_id='{_COMPATIBILITY_BINDING_ID}'
            WHERE vault_binding_id IS NULL;

          ALTER TABLE public.standing_questions ALTER COLUMN vault_binding_id SET NOT NULL;
          ALTER TABLE public.episodes ALTER COLUMN vault_binding_id SET NOT NULL;
          ALTER TABLE public.episode_engine_state ALTER COLUMN vault_binding_id SET NOT NULL;
          ALTER TABLE public.episode_artifact_binding ALTER COLUMN vault_binding_id SET NOT NULL;
          ALTER TABLE public.decisions ALTER COLUMN vault_binding_id SET NOT NULL;
          ALTER TABLE public.decision_outcomes ALTER COLUMN vault_binding_id SET NOT NULL;

          ALTER TABLE public.standing_questions DROP CONSTRAINT standing_questions_pkey;
          ALTER TABLE public.standing_questions DROP CONSTRAINT standing_questions_source_path_key;
          ALTER TABLE public.standing_questions ADD CONSTRAINT standing_questions_pkey
            PRIMARY KEY (vault_binding_id, question_id);
          ALTER TABLE public.standing_questions ADD CONSTRAINT standing_questions_binding_source_key
            UNIQUE (vault_binding_id, source_path);

          ALTER TABLE public.episodes DROP CONSTRAINT episodes_pkey;
          ALTER TABLE public.episodes ADD CONSTRAINT episodes_pkey
            PRIMARY KEY (vault_binding_id, episode_id);

          ALTER TABLE public.episode_engine_state DROP CONSTRAINT episode_engine_state_pkey;
          ALTER TABLE public.episode_engine_state ADD CONSTRAINT episode_engine_state_pkey
            PRIMARY KEY (vault_binding_id, key);

          ALTER TABLE public.episode_artifact_binding
            DROP CONSTRAINT episode_artifact_binding_pkey;
          ALTER TABLE public.episode_artifact_binding
            ADD CONSTRAINT episode_artifact_binding_pkey
            PRIMARY KEY (vault_binding_id, artifact_ref, episode_id);

          ALTER TABLE public.decision_outcomes
            DROP CONSTRAINT decision_outcomes_decision_uuid_rung_index_key;
          ALTER TABLE public.decision_outcomes
            ADD CONSTRAINT decision_outcomes_binding_decision_rung_key
            UNIQUE (vault_binding_id, decision_uuid, rung_index);
        END $mvr05a5$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS standing_questions_binding_status_idx "
        "ON public.standing_questions (vault_binding_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episodes_binding_scope_idx "
        "ON public.episodes (vault_binding_id, scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episode_artifact_binding_binding_episode_idx "
        "ON public.episode_artifact_binding (vault_binding_id, episode_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS decision_outcomes_binding_object_idx "
        "ON public.decision_outcomes (vault_binding_id, decision_object_id)"
    )


def downgrade() -> None:
    raise RuntimeError("MVR-05A5 replay projection binding keys are forward-only")
