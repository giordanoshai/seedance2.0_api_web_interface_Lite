-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.chat_messages (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  conversation_id uuid NOT NULL,
  user_id uuid NOT NULL DEFAULT uid(),
  role text NOT NULL CHECK (role = ANY (ARRAY['user'::text, 'system'::text])),
  text text NOT NULL,
  attachments jsonb DEFAULT '[]'::jsonb,
  task_id uuid,
  video_url text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT chat_messages_pkey PRIMARY KEY (id),
  CONSTRAINT chat_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id),
  CONSTRAINT chat_messages_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id)
);
CREATE TABLE public.conversations (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  user_id uuid NOT NULL DEFAULT uid(),
  title text DEFAULT '新对话'::text,
  thumbnail_url text,
  last_task_id uuid,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT conversations_pkey PRIMARY KEY (id),
  CONSTRAINT conversations_last_task_id_fkey FOREIGN KEY (last_task_id) REFERENCES public.tasks(id)
);
CREATE TABLE public.media_library (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  user_id uuid NOT NULL,
  name text NOT NULL,
  file_type text NOT NULL CHECK (file_type = ANY (ARRAY['image'::text, 'video'::text, 'audio'::text])),
  media_type text,
  file_size integer DEFAULT 0,
  storage_path text NOT NULL,
  thumbnail_path text,
  source_type text NOT NULL CHECK (source_type = ANY (ARRAY['uploaded'::text, 'generated'::text])),
  task_id uuid,
  conversation_id uuid,
  width integer,
  height integer,
  duration integer,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT media_library_pkey PRIMARY KEY (id),
  CONSTRAINT media_library_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id),
  CONSTRAINT media_library_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id),
  CONSTRAINT media_library_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.tasks (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  user_id uuid NOT NULL DEFAULT uid(),
  model text NOT NULL DEFAULT 'doubao-seedance-1-5-pro-251215'::text,
  prompt text,
  input_path text,
  volcano_task_id text,
  status text NOT NULL DEFAULT 'processing'::text,
  ratio text DEFAULT '16:9'::text,
  duration integer DEFAULT 5,
  generate_audio boolean DEFAULT true,
  watermark boolean DEFAULT true,
  content_inputs jsonb DEFAULT '[]'::jsonb,
  video_url text,
  video_signed_url text,
  error_message text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  conversation_id uuid,
  api_request_raw jsonb,
  api_response_raw jsonb,
  CONSTRAINT tasks_pkey PRIMARY KEY (id),
  CONSTRAINT tasks_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id)
);
CREATE TABLE public.user_profiles (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL UNIQUE,
  phone_number text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  display_name text,
  role text,
  CONSTRAINT user_profiles_pkey PRIMARY KEY (id),
  CONSTRAINT user_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
CREATE TABLE public.user_statistics (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  user_id uuid NOT NULL UNIQUE,
  total_video_duration integer DEFAULT 0,
  total_conversations integer DEFAULT 0,
  succeeded_tasks integer DEFAULT 0,
  failed_tasks integer DEFAULT 0,
  total_tasks integer DEFAULT 0,
  total_tasks_processing integer DEFAULT 0,
  total_tasks_queued integer DEFAULT 0,
  total_tasks_running integer DEFAULT 0,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT user_statistics_pkey PRIMARY KEY (id),
  CONSTRAINT user_statistics_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);