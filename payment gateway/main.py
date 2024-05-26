from flask import Flask, request, render_template, jsonify, url_for, current_app
from flask_mail import Mail, Message
import stripe
import webbrowser
import datetime
import requests
import os
import atexit
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)


app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = ""
app.config['MAIL_PASSWORD'] = ""
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False

mail = Mail(app)


stripe.api_key = ""

@app.route('/success')
def success():
    session_id = request.args.get('session_id')
    try:

        session = stripe.checkout.Session.retrieve(session_id)

        subscription_id = session.subscription

        subscription = stripe.Subscription.retrieve(subscription_id)

        customer = stripe.Customer.retrieve(subscription.customer)

        payment_method = stripe.PaymentMethod.retrieve(subscription.default_payment_method)

        invoices = stripe.Invoice.list(subscription=subscription_id, limit=1)
        invoice = invoices.data[0] if invoices.data else None
        invoice_pdf_url = invoice.invoice_pdf if invoice else None


        customer_name = customer.name
        created_date = datetime.datetime.fromtimestamp(subscription.created).strftime('%B %d, %Y %I:%M %p')
        current_period_start = datetime.datetime.fromtimestamp(subscription.current_period_start).strftime('%B %d, %Y')
        current_period_end = datetime.datetime.fromtimestamp(subscription.current_period_end).strftime('%B %d, %Y')
        payment_method_details = f"•••• {payment_method.card.last4}"
        tax_calculation = 'No tax rate applied' if not subscription.default_tax_rates else 'Tax rate applied'


        email_body = f"""
        Success! Payment was successful.

        Customer: {customer_name}
        Created: {created_date}
        Current period: {current_period_start} to {current_period_end}
        ID: {subscription_id}
        Discounts: None
        Billing method: Charge specific payment method
        Payment method: {payment_method_details}
        Tax calculation: {tax_calculation}
        """


        if invoice:
            invoice_date = datetime.datetime.fromtimestamp(invoice.created).strftime('%B %d, %Y %I:%M %p')
            amount_due = invoice.amount_due / 100.0
            email_body += f"\n\nInvoice Details:\nInvoice Date: {invoice_date}\nAmount Due: ${amount_due:.2f}\nInvoice URL: {invoice.hosted_invoice_url}"


        if invoice_pdf_url:
            invoice_pdf = requests.get(invoice_pdf_url)
            invoice_filename = f"{subscription_id}_invoice.pdf"
            with open(invoice_filename, "wb") as f:
                f.write(invoice_pdf.content)


            msg = Message(subject='Subscription Created', sender='', recipients=[customer.email])
            msg.body = email_body
            with app.open_resource(invoice_filename) as attachment:
                msg.attach(invoice_filename, 'application/pdf', attachment.read())


            mail.send(msg)


            os.remove(invoice_filename)
        else:

            msg = Message(subject='Subscription Created', sender='sdharanesh142@gmail.com', recipients=[customer.email])
            msg.body = email_body
            mail.send(msg)

        return render_template(
            'success.html',
            customer_name=customer_name,
            created_date=created_date,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            subscription_id=subscription_id,
            discounts='None',
            billing_method='Charge specific payment method',
            payment_method=payment_method_details,
            tax_calculation=tax_calculation,
            invoice_date=invoice_date if invoice else None,
            amount_due=amount_due if invoice else None,
            invoice_url=invoice.hosted_invoice_url if invoice else None
        )
    except stripe.error.StripeError as e:
        return f'Error retrieving subscription: {e}'

@app.route('/cancel')
def cancel():
    return 'Payment was canceled.'

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        data = request.form
        try:

            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price': data['price_id'],
                        'quantity': 1,
                    },
                ],
                mode='subscription',
                success_url=url_for('success', _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=url_for('cancel', _external=True),
            )

            checkout_url = session.url

            webbrowser.open_new_tab(checkout_url)
        except stripe.error.StripeError as e:
            return f'Error: {e}'

        return ''


    return render_template('checkout_form.html')


def send_notification(customer_email, customer_name, product_name, product_price, subscribed_date, current_period_end):
    with app.app_context():
        msg = Message(
            subject='Your Subscription is About to Expire',
            sender='',
            recipients=[customer_email]
        )
        current_period_end_formatted = datetime.datetime.fromtimestamp(current_period_end).strftime('%B %d, %Y')
        subscribed_date_formatted = datetime.datetime.fromtimestamp(subscribed_date).strftime('%B %d, %Y')
        msg.body = (
            f"Dear {customer_name},\n\n"
            f"Your subscription for {product_name} priced at {product_price} started on {subscribed_date_formatted} "
            f"will expire on {current_period_end_formatted}. Please renew it to continue using our service.\n\n"
            f"Best regards,\nAutointelli"
        )
        mail.send(msg)



def check_subscriptions():
    now = datetime.datetime.now(datetime.timezone.utc)
    threshold = now + datetime.timedelta(days=3)
    timestamp_threshold = int(threshold.timestamp())

    try:

        subscriptions = stripe.Subscription.list(limit=100)
        for subscription in subscriptions.auto_paging_iter():
            if subscription['current_period_end'] < timestamp_threshold:
                customer = stripe.Customer.retrieve(subscription['customer'])
                customer_email = customer['email']
                customer_name = customer.get('name', 'Valued Customer')


                for item in subscription['items']['data']:
                    product = stripe.Product.retrieve(item['price']['product'])
                    product_name = product['name']
                    product_price = f"{item['price']['unit_amount'] / 100:.2f} {item['price']['currency'].upper()}"
                    subscribed_date = subscription['start_date']

                    send_notification(
                        customer_email,
                        customer_name,
                        product_name,
                        product_price,
                        subscribed_date,
                        subscription['current_period_end']
                    )
    except stripe.error.StripeError as e:
        print(f"Error retrieving subscriptions: {e}")


@app.before_request
def before_first_request_func():
    check_subscriptions()


scheduler = BackgroundScheduler()
scheduler.add_job(func=check_subscriptions, trigger="interval", hours=24)
scheduler.start()


atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(debug=True)
