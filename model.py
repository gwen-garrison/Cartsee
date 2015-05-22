"""Models and database functions for Fresh Look"""

from flask_sqlalchemy import SQLAlchemy

from sqlalchemy import func

from datetime import datetime, timedelta
# import numpy
from numpy import array, mean, std


#### copied and pasted from prediction.py ###
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
# from model import db, Order, OrderLineItem, Item
from numpy import array, mean, std
from datetime import datetime, timedelta
###### end prediction.py ####

# from prediction import PredictedCart, MeanDaysBtw, StdDev

db = SQLAlchemy()

### constants for User class methods:
DELIV_HISTORY_MIN_LENGTH = 180 # the minimum order history needed to implement history cutoff
DELIV_HISTORY_USED = 90 # if history cutoff implementd, this is the amount algorithm will go
                        # back in user history to predict cart




class Order(db.Model):
    """Amazon Fresh Order"""

    __tablename__ = "orders"

    amazon_fresh_order_id = db.Column(db.String(30), primary_key=True)
    delivery_date = db.Column(db.DateTime, nullable=False)
    delivery_day_of_week = db.Column(db.String(10), nullable=False)
    delivery_time = db.Column(db.String(30), nullable=False)
    user_gmail = db.Column(db.String(64), db.ForeignKey('users.user_gmail'), nullable=False)

    user = db.relationship("User", backref=db.backref("orders", order_by=amazon_fresh_order_id))

    def calc_order_total(self):
        """Calculates total $ for all line items bought in order"""
        order_total = 0
        for line_item in self.order_line_items:
            order_total += (line_item.unit_price_cents * line_item.quantity)
        return order_total

    def serialize(self):
        """Converts attributes of order object to serialized form convertable to json"""
        return {
            'amazon_fresh_order_id': self.amazon_fresh_order_id,
            'delivery_date': self.delivery_date.strftime("%B %d, %Y"),
            'delivery_day_of_week': self.delivery_day_of_week,
            'delivery_time': self.delivery_time,
            'user_gmail': self.user_gmail,
            'order_line_items_serialized': [order_line_item.serialize() for order_line_item in self.order_line_items],
            'order_total': self.calc_order_total()
        }


    def get_total_qty(self):
        """Returns the total quantity of line items in the order"""

        return len(self.order_line_items)


    def __repr__(self):
        """Representation string"""

        return "<Order amazon_fresh_order_id=%s>" % self.amazon_fresh_order_id


class OrderLineItem(db.Model):
    """Line item from actual Amazon Fresh Order"""

    __tablename__ = "order_line_items"

    order_line_item_id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    amazon_fresh_order_id = db.Column(db.String(30), db.ForeignKey('orders.amazon_fresh_order_id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.item_id'), nullable=False)
    unit_price_cents = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

    order = db.relationship("Order", backref=db.backref("order_line_items", order_by=order_line_item_id))
    item = db.relationship("Item", backref=db.backref("order_line_items", order_by=order_line_item_id))

    def serialize(self):
        """Converts attributes of orderlineitem object to serialized form convertable to json"""

        return {
            'order_line_item_id': self.order_line_item_id,
            'amazon_fresh_order_id': self.amazon_fresh_order_id,
            'item_id': self.item_id,
            'unit_price': self.unit_price_cents,
            'quantity': self.quantity,
            'description': self.item.description
        }

    def __repr__(self):
        """Representation string"""

        return "<OrderLineItem order_line_item_id=%d unit_price_cents=%f qty=%d description=%s>" %   (self.order_line_item_id,
                                                                                self.unit_price_cents,
                                                                                self.quantity,
                                                                                self.item.description)


class SavedCartItem(db.Model):
    """Association between Item and SavedCart"""

    __tablename__ = "saved_carts_items"

    saved_cart_item_id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.item_id"), nullable=False)
    saved_cart_id = db.Column(db.Integer, db.ForeignKey("saved_carts.saved_cart_id"), nullable=False)


class Item(db.Model):
    """Item that can be in an Amazon Fresh Order"""

    __tablename__ = "items"

    item_id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    description = db.Column(db.String(150), nullable=False)

    saved_carts = db.relationship("SavedCart", secondary=SavedCartItem.__tablename__, backref="items")


    def get_last_order_date(self):
        """"Returns the datetime of the last date the item was delivered"""

        return db.session.query(func.max(Order.delivery_date)).join(
                                OrderLineItem).join(Item).filter(
                                Item.item_id==self.item_id).group_by(
                                Item.item_id).one()[0]


    def get_last_price(self):
        """Returns the price (in cents) from the last time the item was ordered"""

        return db.session.query(OrderLineItem.unit_price_cents).join(Item).join(
                                Order).filter(Order.delivery_date==self.get_last_order_date(),
                                              Item.item_id==self.item_id).one()[0]


    def get_deliv_dates(self):
        """Returns an unordered list of datetimes when the item has been delivered"""

        datetimes = []

        # query for list of item descriptions and all the datetimes they were bought:
        datetime_tups =  db.session.query(Order.delivery_date).join(
                                          OrderLineItem).join(Item).filter(
                                          Item.item_id==self.item_id).all()

        for datetime in datetime_tups:
            datetimes.append(datetime[0])

        return datetimes


    def calc_days_btw(self):
        """Calculates and returns the mean number of days between each consecutive
        delivery of the item, and the standard deviation from the mean"""

        days_btw = []

        if len(self.get_deliv_dates()) > 2: # make sure the item has been ordered @ least three times (to get at least two frequencies)
            deliv_dates = sorted(self.get_deliv_dates()) # sort the datetimes so can calculate days between them
            second_last = len(deliv_dates) - 2 # second to last index in delivery dates (finding here so don't have to find for each iteration)

            for i in range(len(deliv_dates)):
                days_btw.append((deliv_dates[i + 1] - deliv_dates[i]).days)
                if i == second_last:
                    break

            days_btw_arr = array(days_btw)

            # not throwing out outliers since we want to know how erratic the days between pattern is:
            return mean(days_btw_arr, axis=0).item(), std(days_btw_arr, axis=0).item() # .item() to convert from numpy object to native python



    def __repr__(self):
        """Representation string"""

        return "<Item item_id=%d description=%s>" % (self.item_id, self.description)



class SavedCart(db.Model):
    """Cart saved by User"""

    __tablename__ = "saved_carts"

    saved_cart_id = db.Column(db.Integer, autoincrement=True, primary_key=True)
    user_gmail = db.Column(db.String(64), db.ForeignKey("users.user_gmail"), nullable=False)

    user = db.relationship("User", backref=db.backref("saved_carts", order_by=saved_cart_id))

    def __repr__(self):
        """Representation string"""

        return "<SavedCart saved_cart_id=%d user_gmail=%s>" % (self.saved_cart_id, self.user_gmail)


class User(db.Model):
    """Amazon Fresh user whose orders are being pulled in from Gmail"""

    __tablename__ = "users"

    user_gmail = db.Column(db.String(64), primary_key=True)
    access_token = db.Column(db.String(150), nullable=False)


    def serialize_orders_for_area_chart(self):
        """Packages user's order dates and totals to pass into D3 area chart function"""
        # TODO: probably should change this entire function to query and move to server (then later to a module)
        # however the strftime would still need to be done at the server.

        date_totals_dict = {}
        order_date_totals = []

        for order in self.orders:
            date_totals_dict[order.delivery_date] = order.calc_order_total()

        sorted_date_totals = sorted(date_totals_dict.keys()) # returns list of sorted dates

        for date in sorted_date_totals:
            order_date_totals.append({"date": date.strftime("%B %d, %Y"),
                                      "close": date_totals_dict[date]})

        return order_date_totals


    def get_items(self):
        """"Gets the complete list of item objects that the user has had delivered"""

        items = []

        for order in self.orders:
            for order_line_item in order.order_line_items:
                items.append(order_line_item.item)

        return set(items)


    def get_first_deliv_date(self):
        """Returns the date of the first delivery in the user's delivery history"""

        return db.session.query(func.min(Order.delivery_date)).filter(
                                Order.user_gmail==self.user_gmail).one()[0]


    def get_last_deliv_date(self):
        """Returns the date of the last delivery in the user's delivery history"""

        return db.session.query(func.max(Order.delivery_date)).filter(
                                Order.user_gmail==self.user_gmail).one()[0]


    def implement_hist_cutoff(self):
        """Determines whether should implement a cutoff of items user last had delivered
        before a certain datetime in order history; if so returns True"""
        # if last delivery has occured relatively recently AND delivery history six months or longer,
        # then limit how far back you look into delivery history to 3 months before last order
        # (implement history cutoff).  Otherwise just use all of delivery history.

        today = datetime.now() #+ timedelta(1000-5)
        # today variable used so can change today's date manually for testing.

        days_deliv_history = (self.get_last_deliv_date() - self.get_first_deliv_date()).days
        days_since_last_deliv = (today - self.get_last_deliv_date()).days

        implement_history_cutoff = False
        if days_since_last_deliv < days_deliv_history and days_deliv_history > DELIV_HISTORY_MIN_LENGTH:
            implement_history_cutoff = True
            print "Implementing item datetime cutoff at %d days before chosen delivery date (Last order is relatively recent and order history > %d days.)" % (
                     DELIV_HISTORY_USED, DELIV_HISTORY_MIN_LENGTH)
        else:
            print "Datetime cutoff NOT being implemented (Order history < 180 days and/or last order occured too long ago).)"  % DELIV_HISTORY_MIN_LENGTH

        return implement_history_cutoff

    def calc_cart_qty(self):
        """Returns the upper limit for number of items that will go in the predicted cart based
        on the mean quantities of order_line_items across the user's delivery history"""

        # calculate the mean order size
        quant_arr = array([order.get_total_qty() for order in user.orders])
        mean_qty = mean(quant_arr, axis=0)
        std_qty = std(quant_arr, axis=0)

        # calculate the adjusted order size after throw out outliers above or below 2 x std dev
        filtered_quants_arr = quant_arr[abs(quant_arr - mean(quant_arr)) < 2 * std(quant_arr)]
        return mean(filtered_quants_arr, axis=0).item()

    def get_min_day_btw(self):
        """Returns the smallest number of days that occurs between items in user's delivery history"""
        # return min([1,2,3])
        return min([(item.calc_days_btw()[0]) for item in self.get_items() if item.calc_days_btw()])
        # if statment in case item.calc_days_btw() is None (if item in only one delivery)
        # throws error if otherwise


    def calc_cart_date(self, date_str):
        """Returns the date the user input for predicted cart delivery, possibly adjusting it
        if too much time has passed since last delivery"""

        # convert the date user wants predicted order to be delivered to datetime and
        input_datetime = datetime.strptime(date_str, "%m/%d/%y")
        # TODO:  this assumes chosen_date_str is input by user as "mm/dd/yy".  Make sure HTML reflects this.

        # difference betwen last delivery date & date user input.
        deliv_day_diff = (input_datetime - self.get_last_deliv_date()).days

        days_deliv_history = (self.get_last_deliv_date() - self.get_first_deliv_date()).days

        # if the time since your last delivery is greater than your entire delivery
        # history, the algorithm won't work.  So here the chosen datetime for the
        # predicted cart is shifted to act as if the orders occured more recently.
        # The user won't know the date used for the prediction has changed.
        if deliv_day_diff >= days_deliv_history:
            # to make sure prediction is possible chosen date set within prediction range:
            adj_datetime = self.get_last_deliv_date() + timedelta(days=self.get_min_day_btw())
            print "Adjusting datetime used for prediction, to account for delivery history occuring too long ago"

        else:
            adj_datetime = input_datetime
            print "Original datetime input by user being used to predict cart"

        return adj_datetime


    def calc_cutoff(self, date_str):
        """Calculates the datetime lower cutoff for cart prediction algorithm"""

        adj_datetime = self.calc_cart_date(date_str)

        # Only items that are bought with a mean days btw of at least 80% of the # of days between
        # last deliv and predicted deliv will be added to the predicted cart
        adj_deliv_day_diff = (adj_datetime - self.get_last_deliv_date()).days

        return (80 * adj_deliv_day_diff)/100

    def predict_cart(self, date_str):
        """Appends user's items to predicted cart contents that meet frequency cutoff,
        from lowest std devs to highest, until qty cutoff is reached."""

        cart = PredictedCart()
        std_map = {} # {std_key: {mean_key: [item obj, item obj, ...], ...}, ...}

        for item in self.get_items():
            if item.calc_days_btw():
                mean, std = item.calc_days_btw()
                std_key = int(std)
                mean_key = int(mean)
                std_map.setdefault(std_key, {})
                std_map[std_key].setdefault(mean_key, [])
                std_map[std_key][mean_key].append(item)
            else:
                continue




        # mean_list = []
        # # for each item that the user bought, extract the mean days between each
        # # deliv and the std from the mean, then make the std_map {std value: std obj}
        # for item in self.get_items():
        #     if item.calc_days_btw():
        #         mean, std = item.calc_days_btw()
        #         # mean_list.append(mean)
        #         std_key = int(std)
        #         # mean_key = int(mean)
        #         std_map.setdefault(std_key, StdDev(std))
        #
        #         # # update the std_obj attribute mean_days_map (dict of {mean value: mean_days_obj})
        #         # std_map[std_key].mean_days_map.setdefault(mean_key, MeanDaysBtw(mean))
        #         # # std_map[std_key].add_mean_days(mean)
        #         #
        #         # # mean_days_key = int(mean)
        #         #
        #         # # update the mean_days obj attribute items (list)
        #         # std_map[std_key].mean_days_map[mean_key].add_item(item)
        #     else:
        #         continue

        # for item in self.get_items():
        #     if item.calc_days_btw():
        #         mean, std = item.calc_days_btw()
        #         std_key = int(std)
        #         std_map[std_key].mean_days.append[MeanDaysBtw(mean)]
        #     else:
        #         continue

        print std_map

        # for std_key in std_map.keys():
        #     print std_map[std_key].mean_days
        #
        #
        #
        # sorted_stds = sorted(std_map) # sort the std_map keys from lowest (best) to highest (worst)
        #
        # days_btw_cutoff = user.calc_cutoff(date_str)
        # cart_qty = user.calc_cart_qty()
        #
        # for std in sorted_stds:
        #
        #     for items in std_map[std_key][mean_key]:
        #         items_to_add = std_map[std_key].mean_days_map[mean_key].items
        #         if mean_days >= days_btw_cutoff:
        #             spaces_left = cart.calc_spaces_left(cart_qty)
        #
        #             if len(items_to_add) >= spaces_left:
        #                 cart.contents.extend(items_to_add[:spaces_left])
        #                 cart.check_contents()
        #                 return cart.contents
        #         cart.contents.extend(items_to_add)


class PredictedCart(object):
    contents = []

    def calc_spaces_left(self, mean_days_btw):
        """Calculates the spaces left in the predicted cart"""

        return int(mean_days_btw - len(self.contents))


    def check_contents(self):
        """Prints statements reflecting whether cart has been filled, or says
        cart can't be predicted if it's empty"""

        if self.contents:
            print "Cart has been filled with predicted items."
        else:
            print "Sorry, we cannot predict your cart at this time."


    def __repr__(self):
        """Representation string"""

        return "<User user_gmail=%s>" % self.user_gmail

class MeanDaysBtw(object):
    items = []

    def __init__(self, value):
        self.value = value

    def add_item(self, item):
        """Appends an item object with the value of the mean freq object to the
        items list."""

        self.items.append(item)

    def __repr__(self):
        """Representation string"""

        return "<MeanDaysBtw value=%.2f>" % self.value


class StdDev(object):
    mean_days = [] # {mean_day value: mean_day obj}

    def __init__(self, value):
        self.value = value

    # def add_mean_days(self, mean_days):
    #     """Appends a mean_days_btw object with the value of the std
    #     dev object to the mean_days_btw list, if the mean_days_btw not already in there"""
    #
    #     mean_days_obj = MeanDaysBtw(mean_days)
    #
    #     mean_days_value = int(mean_days_obj.value)
    #
    #     self.mean_days_map.setdefault(mean_days_value, mean_days_obj)

    def __repr__(self):
        """Representation string"""

        return "<StdDev value=%.2f>" % self.value




##############################################################################
# Helper functions

    # this creats session and binds session to engine? so
    # binds engine to the database and we don't need to do the following...?
    # from sqlalchemy import create_engine
    # Base.metadata.create_all(engine)
    # DB_URI = "sqlite:///freshlook.db"
    # engine = create_engine(DB_URI, echo=True)
    # from sqlalchemy.orm import sessionmaker
    # Session = sessionmaker(bind=engine)
    # session = Session()


if __name__ == "__main__":
    # As a convenience, if we run this module interactively, it will leave
    # you in a state of being able to work with the database directly.

    from server import app, connect_to_db
    connect_to_db(app, db, "freshlook.db")


    # TODO:  figure out where to put create the engine and the session
    # engine = create_engine(DB_URI, echo=True)
