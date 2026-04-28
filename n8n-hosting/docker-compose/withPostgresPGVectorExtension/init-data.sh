#!/bin/bash
set -e;


if [ -n "${POSTGRES_NON_ROOT_USER:-}" ] && [ -n "${POSTGRES_NON_ROOT_PASSWORD:-}" ]; then
	psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
		CREATE USER ${POSTGRES_NON_ROOT_USER} WITH PASSWORD '${POSTGRES_NON_ROOT_PASSWORD}';
		GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_NON_ROOT_USER};
		GRANT CREATE ON SCHEMA public TO ${POSTGRES_NON_ROOT_USER};
	EOSQL
	
	# Create vector extension, embeddings and app tables
	echo "Creating vector extension and embeddings table..."
	if ! psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
		CREATE EXTENSION IF NOT EXISTS vector;

		CREATE TABLE IF NOT EXISTS embeddings (
		  id SERIAL PRIMARY KEY,
		  embedding vector,
		  text text,
		  created_at timestamptz DEFAULT now()
		);

		-- Create uploaded_files table
		CREATE TABLE IF NOT EXISTS uploaded_files (
		  id text PRIMARY KEY,
		  file_name text,
		  author_name text DEFAULT null,
		  author_email text DEFAULT null,
		  processing boolean DEFAULT false,
		  is_processed boolean DEFAULT false,
		  created_at timestamptz DEFAULT now()
		);

		-- Create transcriptions table
		CREATE TABLE IF NOT EXISTS transcriptions (
		  id SERIAL PRIMARY KEY,
		  timestamp timestamptz DEFAULT now(),
		  file_name text,
		  author_name text DEFAULT null,
		  author_email text DEFAULT null,
		  content text,
		  summarized_content text DEFAULT null,
		  processing boolean DEFAULT false,
		  is_processed boolean DEFAULT false
		);
		
		-- Create user_stories table
		CREATE TABLE IF NOT EXISTS user_stories (
		  id SERIAL PRIMARY KEY,
		  timestamp timestamptz DEFAULT now(),
		  title text,
		  description text,
		  processed_description text DEFAULT null,
		  created_for_name text DEFAULT 'Everyone',
  		  created_for_email text DEFAULT 'everyone@org.com',
		  processing boolean DEFAULT false,
		  is_processed boolean DEFAULT false
		);
		
		-- Create notifications table
		CREATE TABLE IF NOT EXISTS notifications (
		  id SERIAL PRIMARY KEY,
		  timestamp timestamptz DEFAULT now(),
		  message text,
		  is_app_msg boolean DEFAULT true,
		  type text,
		  for_user_email text DEFAULT 'everyone@org.com',
		  processing boolean DEFAULT false,
		  is_processed boolean DEFAULT false
		);

		-- Create actions table with user_story_id as a foreign key
		CREATE TABLE IF NOT EXISTS actions (
			id SERIAL PRIMARY KEY,
			timestamp timestamptz DEFAULT now(),
			type text NOT NULL, -- e.g., 'create-clickup-ticket', 'create-git-issue', etc.
			processing boolean DEFAULT false,
			is_processed boolean DEFAULT false,
			user_story_id integer,
			CONSTRAINT fk_actions_user_story
				FOREIGN KEY (user_story_id)
				REFERENCES user_stories(id)
				ON DELETE SET NULL
		);

		CREATE TABLE IF NOT EXISTS mentor_mind_logs (
		  id SERIAL PRIMARY KEY,
		  timestamp timestamptz DEFAULT now(),
		  message text,
		  type text
		);
	EOSQL
	then
		echo "ERROR: Failed to create tables"
		exit 1
	fi
	echo "All tables created successfully"
else
	echo "SETUP INFO: No Environment variables given!"
fi
