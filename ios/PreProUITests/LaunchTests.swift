import XCTest

/// The test build starts on an iPhone and shows what a tester needs: the build number, the clip-time check and the
/// test report.
final class LaunchTests: XCTestCase {
    func testTheStartScreenShowsTheBuildTheCheckAndTheReport() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.staticTexts["build-label"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["build-label"].label.hasPrefix("Build "))
        XCTAssertTrue(app.buttons["choose-clips"].exists)
        XCTAssertTrue(app.buttons["send-report"].exists)
    }
}
