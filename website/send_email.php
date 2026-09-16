<?php
if ($_SERVER["REQUEST_METHOD"] === "POST") {
    $name = trim($_POST['name'] ?? '');
    $email = trim($_POST['email'] ?? '');
    $subject = trim($_POST['subject'] ?? '');
    $message = trim($_POST['message'] ?? '');

    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        http_response_code(400);
        exit("Invalid email address.");
    }

    // Prevent mail-header injection.
    if (
        preg_match('/[\r\n]/', $name) ||
        preg_match('/[\r\n]/', $email) ||
        preg_match('/[\r\n]/', $subject)
    ) {
        http_response_code(400);
        exit("Invalid input.");
    }

    $to = 'contact.makaao@inria.fr';
    // test address: test.makaao@inria.fr
    // real address: contact.makaao@inria.fr

    $headers =
        "From: MAKAAO Website <contact.makaao@inria.fr>\r\n" .
        "Reply-To: $email\r\n";

    if (mail($to, $subject, $message, $headers)) {
        echo "Email sent successfully!";
    } else {
        http_response_code(500);
        echo "Failed to send email.";
    }
}
?>
