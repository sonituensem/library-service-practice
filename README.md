# Library Service

A Django REST Framework API for managing a library's books, customers, and borrowings.
This repository is the Flex practice project; no front-end is included.

## Project workflow

- Implement each selected task on its own clearly named branch.
- Commit small, complete changes throughout the task.
- Open a separate pull request to `main` for each coding task.
- Keep credentials and local configuration out of Git.

## Selected implementation scope

The selected tasks cover user registration and JWT authentication, book
inventory, book permissions, the borrowing lifecycle, Stripe payments, Telegram
notifications, overdue fines, and Docker Compose. Tests, Swagger documentation,
test coverage reporting, and a complete README are project-wide requirements.

The implemented API endpoints and project commands are documented below.

## Telegram notifications

The borrowing API queues a Telegram notification after a new borrowing has
been committed to the database. The message includes the borrowing id,
customer, book, borrowing date, and expected return date. Telegram delivery
runs in a Celery worker, so the API request does not wait for Telegram.

1. Create a bot with Telegram's BotFather and add it to the administrators'
   chat. Copy `.env.sample` to `.env` (in PowerShell, run
   `Copy-Item .env.sample .env`) and set `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_CHAT_ID`. Keep `.env` private; it is ignored by Git.
2. Start Redis at the address configured by `CELERY_BROKER_URL`.
3. Start the Django API with `python manage.py runserver`.
4. In another terminal, start a worker:

   ```shell
   celery -A config worker --loglevel=INFO --pool=solo
   ```

The `--pool=solo` option is for local development on Windows. The notification
tests mock Telegram requests and do not require a bot token or live Telegram
chat.

Celery Beat checks overdue borrowings every day at 09:00 UTC. It queues one
message for each borrowing whose expected return date is today or earlier and
that has not been returned. When none are overdue, it queues
`No borrowings overdue today!`. Run one scheduler process in another terminal:

```shell
celery -A config beat --loglevel=INFO
```

## Local setup

```shell
python -m venv .venv
```

Activate the virtual environment, then install dependencies and prepare the database:

```shell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The API is available below `/api/`.

To create a staff account for the staff-only book write endpoints, run this
command in a separate terminal and follow the prompts:

```shell
python manage.py createsuperuser
```

Registering through the public users API creates a regular customer account;
it cannot grant staff access.

## Docker Compose setup

The Compose stack runs the API, PostgreSQL, Redis, a Celery worker, and Celery
Beat. It waits for PostgreSQL and Redis health checks, runs migrations once,
then starts the API and background processes.

Copy the sample environment file, then change the local Django secret and
PostgreSQL password:

```powershell
Copy-Item .env.sample .env
```

Start all services in the background:

```shell
docker compose up --build -d
docker compose ps --all
```

The API and Swagger UI are available at `http://localhost:8000/api/` and
`http://localhost:8000/api/docs/`. Check the database migrations and API from
inside the running service:

```shell
docker compose exec api python manage.py check
docker compose exec api python manage.py migrate --check
docker compose exec api python manage.py createsuperuser
```

Check that the background worker answers Celery's control ping and inspect
worker/scheduler logs:

```shell
docker compose exec worker celery -A config inspect ping
docker compose logs worker beat
```

The PostgreSQL data is stored in the `postgres_data` volume. `docker compose
down` stops the services but preserves the database; `docker compose down -v`
also deletes that data. Compose sets `DB_ENGINE`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST`, and `DB_PORT` for the application containers. Outside
Compose, the project continues to use its local SQLite database by default.

## Users API

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| `POST` | `/api/users/` | Register with email, password, and optional first/last name | Public |
| `POST` | `/api/users/token/` | Obtain an access and refresh JWT using email and password | Public |
| `POST` | `/api/users/token/refresh/` | Obtain a new access JWT using a refresh token | Public |
| `GET` | `/api/users/me/` | Retrieve the authenticated user's profile | JWT |
| `PUT`, `PATCH` | `/api/users/me/` | Update email, password, first name, or last name | JWT |

Register with `POST /api/users/` and a JSON body containing `email` and
`password`. `first_name` and `last_name` are optional:

```json
{
  "email": "reader@example.com",
  "password": "StrongPass9#",
  "first_name": "Alex",
  "last_name": "Reader"
}
```

The response is `201 Created` with the user's `id`, `email`, `first_name`, and
`last_name`. To sign in, send `{"email": "reader@example.com", "password":
"StrongPass9#"}` to `POST /api/users/token/`; the response contains `access`
and `refresh` tokens. Send `{"refresh": "<refresh-token>"}` to
`POST /api/users/token/refresh/` to obtain a new `access` token.

Send the access token in the `Authorize` header using the `Bearer` scheme:

```http
Authorize: Bearer <access-token>
```

`GET /api/users/me/` returns the current user's profile. Send any of `email`,
`password`, `first_name`, or `last_name` in a JSON body to
`PUT /api/users/me/` or `PATCH /api/users/me/` to update it. Both update
methods accept omitted fields and return the updated profile. Duplicate emails
and weak passwords return `400 Bad Request` with field errors.

Passwords are validated with Django's configured password validators, stored
as hashes, and never returned by the API. The `is_staff` flag is never editable
through these endpoints.

## Books API

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/api/books/` | List all books and their available inventory | Public |
| `POST` | `/api/books/` | Add a book | Staff JWT |
| `GET` | `/api/books/<id>/` | Retrieve one book | Public |
| `PUT`, `PATCH` | `/api/books/<id>/` | Replace or update a book, including its inventory | Staff JWT |
| `DELETE` | `/api/books/<id>/` | Delete a book | Staff JWT |

Use a JSON body for `POST` and `PUT`; `PATCH` accepts only the fields to change:

```json
{
  "title": "The Hobbit",
  "author": "J. R. R. Tolkien",
  "cover": "HARD",
  "inventory": 3,
  "daily_fee": "1.25"
}
```

`cover` accepts `HARD` or `SOFT`. `inventory` is a nonnegative integer: zero
means no copies are currently available. `daily_fee` is a nonnegative USD
decimal with two fractional digits. Responses include the book's generated
`id`. Invalid field values return `400 Bad Request`; an unknown book id returns
`404 Not Found`. Anyone can read the catalogue. Create, update, and delete
requests require a JWT for a staff user; anonymous and non-staff users receive
an authorization error for write requests.

## Borrowings API

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| `POST` | `/api/borrowings/` | Borrow an available book | JWT |
| `GET` | `/api/borrowings/` | List visible borrowing records | JWT |
| `GET` | `/api/borrowings/<id>/` | Retrieve one borrowing with its book details | JWT |
| `POST` | `/api/borrowings/<id>/return/` | Return a borrowed book | JWT |

Create a borrowing with `book_id` and `expected_return_date`:

```json
{
  "book_id": 1,
  "expected_return_date": "2026-11-01"
}
```

The server sets `borrow_date` to the current local date and assigns the
authenticated user. The client cannot set the borrower or actual return date.
If the book has no available copies, the request returns `400 Bad Request` and
does not create a borrowing. A successful request reserves one copy by
decrementing the book's `inventory`. It also creates a pending Stripe `PAYMENT`
for `daily_fee` multiplied by the number of calendar days between the borrowing
and expected return dates. The response includes the payment amount and Checkout
session URL/id. If Stripe is not configured or cannot create a session, the API
returns `503 Service Unavailable` and rolls back the borrowing and inventory
reservation.

Return an active borrowing with an empty `POST` request to
`/api/borrowings/<id>/return/`. The server sets `actual_return_date` to the
current local date and restores one copy to the book's `inventory`. A borrowing
cannot be returned twice; a repeated request returns `400 Bad Request` without
changing the inventory. If the return date is later than the expected return
date, the same transaction also creates a pending `FINE` payment. The amount is
the overdue days multiplied by the book's daily fee and `FINE_MULTIPLIER`
(default `2`), rounded to cents using half-up rounding. Set `FINE_MULTIPLIER` in
`.env` to change the policy. Customers can return only their own borrowings;
staff users can return any borrowing.

Customers see only their own borrowing records; staff users can see all records.
Each response includes the borrower id, borrowing dates, and a nested `book`
object with the book's current inventory information, plus the associated
payment records.

## Payments API

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/api/payments/` | List visible payment records | JWT |
| `GET` | `/api/payments/<id>/` | Retrieve one payment | JWT |
| `GET` | `/api/payments/success/?session_id=...` | Verify Checkout and confirm payment | Stripe redirect |
| `GET` | `/api/payments/cancel/` | Explain how to resume a canceled Checkout | Stripe redirect |

Customers see payment records linked to their own borrowings. Staff users can
list and retrieve all payment records. The response includes `status` (`PENDING`
or `PAID`), `type` (`PAYMENT` or `FINE`), the borrowing id, Stripe session URL
and id, and the amount in USD. Payment records are read-only through this API;
the borrowing and return endpoints create pending payment records. A late
return creates a `FINE` record that appears in the same payment list and
borrowing response. The success endpoint
retrieves the session from Stripe and marks a payment `PAID` only after Stripe
confirms it. The cancel endpoint leaves it pending and explains that the same
Checkout link remains available for 24 hours. Confirmed payments also queue an
administrator Telegram notification with the borrowing and amount details.

## Stripe test setup

Copy `.env.sample` to `.env` and set `STRIPE_SECRET_KEY` to a Stripe test-mode
secret key (`sk_test_...`). New borrowings create one hosted Checkout line item
in USD. Stripe success and cancel URLs are built from the API request and named
routes. Tests mock Stripe and do not require a Stripe account or make external
requests. Never add a live key or any Stripe secret to Git.

For the manual learning step, create a Checkout Session with Stripe's Python
SDK in test mode, then create a `Payment` in Django admin using that session's
URL and id. Link it to a borrowing and check it with `GET /api/payments/` and
`GET /api/payments/<id>/`. The payment API remains read-only for customers.

## API documentation

Interactive Swagger UI is available at `/api/docs/` and the OpenAPI schema at
`/api/schema/`. In Swagger UI, enter `Bearer <access-token>` in the `Authorize`
authentication field before trying protected operations.

## Tests and coverage

```shell
coverage run manage.py test
coverage report
```
